# Pico USB Display Bridge

This document describes how to use InkyPi with a Raspberry Pi Pico connected over USB as a display bridge.

## Status

InkyPi includes a `pico_usb` display backend that sends full frames over a serial USB link.  
You must run matching firmware on the Pico to receive and render frames on the e-paper panel.

## Device configuration

In `src/config/device.json` set:

```json
{
  "display_type": "pico_usb",
  "resolution": [800, 480],
  "pico_port": "/dev/ttyACM0",
  "pico_baudrate": 115200,
  "pico_timeout_sec": 15,
  "pico_handshake_timeout_sec": 5
}
```

Adjust `resolution` to your panel.

## Serial protocol (`inkypi-v1`)

From host (InkyPi) to Pico:

1. `PING\n`
2. `FRAME <width> <height> RGB888 <payload_len>\n`
3. raw payload bytes (`width * height * 3`)

From Pico back to host:

- `PONG\n` for handshake success
- `OK\n` after frame accepted and rendered
- `ERR <reason>\n` on failure

## Debug tips

- Confirm USB serial device exists (`/dev/ttyACM0`, `/dev/ttyACM1`, etc).
- Ensure the InkyPi service user can access that device.
- If handshake fails, check Pico firmware logs and verify it replies with `PONG`.
- If frame transfer fails, verify Pico expects `RGB888` and exact payload length.
