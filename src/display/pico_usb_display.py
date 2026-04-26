import logging
import time

from .abstract_display import AbstractDisplay

logger = logging.getLogger(__name__)


class PicoUsbDisplay(AbstractDisplay):
    """
    Display backend for a USB-connected Raspberry Pi Pico e-paper bridge.

    Protocol (inkypi-v1):
      1) Host sends: PING\\n
      2) Pico responds: PONG\\n
      3) Host sends: FRAME <width> <height> RGB888 <bytes>\\n
      4) Host sends raw RGB888 payload bytes (width*height*3)
      5) Pico responds: OK\\n (or ERR <reason>\\n)
    """

    DEFAULT_RESOLUTION = [800, 480]

    def initialize_display(self):
        try:
            import serial
        except ImportError as exc:
            raise ValueError(
                "Pico USB display requires pyserial. Install it in the InkyPi venv."
            ) from exc

        self._serial = serial
        self.port = self.device_config.get_config("pico_port", "/dev/ttyACM0")
        self.baudrate = int(self.device_config.get_config("pico_baudrate", 115200))
        self.timeout_sec = float(self.device_config.get_config("pico_timeout_sec", 15))
        self.handshake_timeout_sec = float(
            self.device_config.get_config("pico_handshake_timeout_sec", 5)
        )

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
        self._handshake()

    def _open_serial(self):
        try:
            conn = self._serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1,
                write_timeout=self.timeout_sec,
            )
            # Give MicroPython/CircuitPython firmware time to settle after open.
            time.sleep(0.5)
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
        self.serial_conn.write(b"PING\n")
        self.serial_conn.flush()

        response = self._readline(self.handshake_timeout_sec)
        if response != "PONG":
            raise ValueError(
                f"Pico handshake failed on {self.port}. Expected 'PONG', got '{response or '<empty>'}'."
            )
        logger.info("Pico USB handshake successful.")

    def _ensure_connection(self):
        if self.serial_conn and self.serial_conn.is_open:
            return
        self.serial_conn = self._open_serial()
        self._handshake()

    def display_image(self, image, image_settings=[]):
        if image is None:
            raise ValueError("No image provided.")

        self._ensure_connection()

        # Device-specific rendering work is expected on the Pico side.
        # We send raw RGB data to avoid adding host-side format assumptions.
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        payload = rgb_image.tobytes()

        header = f"FRAME {width} {height} RGB888 {len(payload)}\n".encode("ascii")
        try:
            self.serial_conn.reset_input_buffer()
            self.serial_conn.write(header)
            self.serial_conn.write(payload)
            self.serial_conn.flush()
        except Exception as exc:
            raise ValueError(f"Failed to write frame to Pico: {exc}") from exc

        response = self._readline(self.timeout_sec)
        if response != "OK":
            raise ValueError(
                f"Pico rejected frame update. Response: '{response or '<empty>'}'"
            )

        logger.info(
            "Frame sent to Pico over USB (%sx%s, %s bytes).",
            width,
            height,
            len(payload),
        )
