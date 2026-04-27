import sys
import time

# Simple USB-serial protocol bridge for InkyPi (inkypi-v1)
# Commands:
#   PING\n                          -> PONG\n
#   FRAME w h RGB888 bytes\n + bin  -> OK\n (after consuming payload)
#   Unknown                         -> ERR ...\n

stdin = sys.stdin.buffer
stdout = sys.stdout

def writeln(msg: str):
    stdout.write(msg + "\n")
    stdout.flush()

def read_line(timeout_s=10):
    start = time.ticks_ms()
    buf = bytearray()
    while True:
        if stdin.peek(1):
            b = stdin.read(1)
            if not b:
                continue
            if b == b"\n":
                return buf.decode("utf-8", "replace").strip()
            buf.extend(b)
        else:
            time.sleep_ms(2)

        if time.ticks_diff(time.ticks_ms(), start) > int(timeout_s * 1000):
            return None

def read_exact(n: int):
    remaining = n
    while remaining > 0:
        chunk = stdin.read(remaining if remaining < 4096 else 4096)
        if not chunk:
            time.sleep_ms(1)
            continue
        remaining -= len(chunk)

def handle_frame(cmd: str):
    # Expected: FRAME <w> <h> RGB888 <len>
    parts = cmd.split()
    if len(parts) != 5:
        writeln("ERR bad_header_parts")
        return
    _, w, h, fmt, payload_len = parts
    if fmt != "RGB888":
        writeln("ERR bad_format")
        return
    try:
        payload_len = int(payload_len)
        int(w); int(h)
    except:
        writeln("ERR bad_numbers")
        return

    # Consume payload so host doesn't block.
    # (Rendering hook comes next.)
    read_exact(payload_len)
    writeln("OK")

def main():
    # USB CDC can need a moment after boot
    time.sleep(1.0)
    writeln("READY")

    while True:
        line = read_line(timeout_s=3600)
        if line is None:
            continue
        if line == "PING":
            writeln("PONG")
        elif line.startswith("FRAME "):
            handle_frame(line)
        else:
            writeln("ERR unknown_command")

main()