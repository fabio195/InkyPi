import logging
import os
import time

from .abstract_display import AbstractDisplay
from PIL import Image

logger = logging.getLogger(__name__)


class PicoUsbDisplay(AbstractDisplay):
    """
    Display backend for a USB-connected Raspberry Pi Pico e-paper bridge.

    Protocol (inkypi-v1):
      1) Host sends: PING\\n
      2) Pico responds: PONG\\n
      3) Host sends: FRAME <width> <height> BWR2 <black_bytes> <red_bytes>\\n
      4) Host sends packed 1bpp black plane bytes, then packed 1bpp red plane bytes
      5) Pico responds: OK\\n (or ERR <reason>\\n)
    """

    DEFAULT_RESOLUTION = [800, 480]

    def _pack_1bpp(self, img_1bit):
        if img_1bit.mode != "1":
            raise ValueError("Expected 1-bit image (mode '1').")
        width, height = img_1bit.size
        expected_len = ((width + 7) // 8) * height
        data = img_1bit.tobytes()
        if len(data) != expected_len:
            raise ValueError(
                f"Unexpected packed length for 1bpp image: got {len(data)}, expected {expected_len}"
            )
        return data

    def _split_bwr_layers(self, image):
        # Use the same approach as Waveshare bi-color splitting (black + red).
        black = (0, 0, 0)
        white = (255, 255, 255)
        red = (255, 0, 0)

        palette_data = [*black, *white, *red]
        palette_img = Image.new("P", (1, 1))
        palette_img.putpalette(palette_data)

        rgb = image.convert("RGB")
        indexed = rgb.quantize(palette=palette_img, dither=Image.Dither.FLOYDSTEINBERG)
        black_layer = indexed.point(lambda p: 0 if p == 0 else 1, mode="1")
        red_layer = indexed.point(lambda p: 0 if p == 2 else 1, mode="1")
        return black_layer, red_layer

    def initialize_display(self):
        try:
            import serial
        except ImportError as exc:
            raise ValueError(
                "Pico USB display requires pyserial. Install it in the InkyPi venv."
            ) from exc

        self._serial = serial
        self.port = self.device_config.get_config("pico_port", "/dev/ttyACM0")
        self.prefer_data_port = bool(self.device_config.get_config("pico_prefer_data_port", True))
        if (
            self.prefer_data_port
            and self.port == "/dev/ttyACM0"
            and os.path.exists("/dev/ttyACM1")
        ):
            # MicroPython can expose usb_cdc.console + usb_cdc.data as two ACM devices.
            # Prefer the data channel for binary transfers.
            self.port = "/dev/ttyACM1"
            logger.info("Pico USB data port detected; using %s", self.port)
        self.baudrate = int(self.device_config.get_config("pico_baudrate", 115200))
        # Total transfer for 800x480 BWR2 is ~96KB, which can take 10s-60s depending on
        # baud, USB CDC buffering, and MicroPython overhead. Use a safer default.
        self.timeout_sec = float(self.device_config.get_config("pico_timeout_sec", 180))
        self.handshake_timeout_sec = float(
            self.device_config.get_config("pico_handshake_timeout_sec", 5)
        )
        self.handshake_retries = int(
            self.device_config.get_config("pico_handshake_retries", 5)
        )
        self.handshake_enabled = bool(
            self.device_config.get_config("pico_handshake_enabled", True)
        )
        self.boot_wait_sec = float(self.device_config.get_config("pico_boot_wait_sec", 2))
        self.write_timeout_sec = float(
            self.device_config.get_config("pico_write_timeout_sec", 60)
        )
        self.tx_chunk_size = int(self.device_config.get_config("pico_tx_chunk_size", 4096))
        self.tx_chunk_delay_ms = int(self.device_config.get_config("pico_tx_chunk_delay_ms", 1))

        # The rest of InkyPi expects a configured resolution from the device config.
        if not self.device_config.get_config("resolution"):
            self.device_config.update_value(
                "resolution", self.DEFAULT_RESOLUTION, write=True
            )
            logger.warning(
                "No resolution configured for pico_usb; defaulting to %sx%s",
                self.DEFAULT_RESOLUTION[0],
                self.DEFAULT_RESOLUTION[1],
            )

        logger.info(
            "Initializing Pico USB display on %s @ %s baud", self.port, self.baudrate
        )
        self.serial_conn = self._open_serial()
        if self.handshake_enabled:
            self._handshake()
        else:
            logger.warning(
                "Pico handshake disabled by config (pico_handshake_enabled=false)."
            )

    def _open_serial(self):
        try:
            conn = self._serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1,
                write_timeout=self.write_timeout_sec,
            )
            # Opening CDC can reset some Pico firmwares; allow boot/banner time.
            time.sleep(self.boot_wait_sec)
            return conn
        except Exception as exc:
            raise ValueError(f"Failed to open Pico serial port '{self.port}': {exc}") from exc

    def _readline(self, timeout_sec):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            line = self.serial_conn.readline()
            if line:
                return line.decode("utf-8", errors="replace").strip()
        return ""

    def _handshake(self):
        self.serial_conn.reset_input_buffer()
        # Ignore early boot chatter/banner lines from firmware.
        _ = self._readline(0.3)

        for attempt in range(1, self.handshake_retries + 1):
            self.serial_conn.write(b"PING\n")
            self.serial_conn.flush()
            response = self._readline(self.handshake_timeout_sec)
            if response == "PONG":
                logger.info("Pico USB handshake successful.")
                return

            logger.warning(
                "Pico handshake attempt %s/%s failed (got '%s').",
                attempt,
                self.handshake_retries,
                response or "<empty>",
            )
            time.sleep(0.5)

        raise ValueError(
            f"Pico handshake failed on {self.port} after {self.handshake_retries} attempts. "
            "Expected 'PONG'. Check Pico firmware protocol or set "
            "'pico_handshake_enabled': false to skip startup handshake."
        )

    def _ensure_connection(self):
        if self.serial_conn and self.serial_conn.is_open:
            return
        self.serial_conn = self._open_serial()
        if self.handshake_enabled:
            self._handshake()

    def _write_all(self, payload):
        total = len(payload)
        sent = 0
        while sent < total:
            chunk = payload[sent : sent + self.tx_chunk_size]
            written = self.serial_conn.write(chunk)
            if written is None:
                written = 0
            if written <= 0:
                raise ValueError("Serial write returned zero bytes; Pico not reading data.")
            sent += written
            if self.tx_chunk_delay_ms > 0:
                time.sleep(self.tx_chunk_delay_ms / 1000.0)

    def display_image(self, image, image_settings=[]):
        if image is None:
            raise ValueError("No image provided.")

        self._ensure_connection()

        width, height = image.size

        black_layer, red_layer = self._split_bwr_layers(image)
        black_payload = self._pack_1bpp(black_layer)
        red_payload = self._pack_1bpp(red_layer)

        header = (
            f"FRAME {width} {height} BWR2 {len(black_payload)} {len(red_payload)}\n"
        ).encode("ascii")
        try:
            self.serial_conn.reset_input_buffer()
            self._write_all(header)
            # Wait until Pico validates header and is ready, to avoid overrunning
            # small firmware input buffers.
            rdy_deadline = time.time() + self.timeout_sec
            rdy = ""
            while time.time() < rdy_deadline:
                rdy = self._readline(1)
                if rdy in ("RDY", "OK") or rdy.startswith("ERR"):
                    break
            if rdy.startswith("ERR"):
                raise ValueError(f"Pico rejected frame header. Response: '{rdy}'")
            if rdy not in ("RDY", "OK"):
                raise ValueError("Pico did not respond RDY to frame header.")

            self._write_all(black_payload)
            self._write_all(red_payload)
            self.serial_conn.flush()
        except Exception as exc:
            raise ValueError(
                f"Failed to write frame to Pico: {exc}. "
                "The Pico firmware may not be reading USB serial data or expects a different protocol."
            ) from exc

        # Pico may emit boot/debug chatter; read until OK/ERR or timeout.
        deadline = time.time() + self.timeout_sec
        response = ""
        while time.time() < deadline:
            response = self._readline(1)
            if response in ("OK",) or response.startswith("ERR"):
                break

        if response != "OK":
            raise ValueError(f"Pico rejected frame update. Response: '{response or '<empty>'}'")

        logger.info(
            "Frame sent to Pico over USB (%sx%s, black=%s bytes, red=%s bytes).",
            width,
            height,
            len(black_payload),
            len(red_payload),
        )
