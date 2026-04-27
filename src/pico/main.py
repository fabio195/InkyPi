import sys
import time
import uselect

stdin = sys.stdin.buffer
stdout = sys.stdout
poller = uselect.poll()
poller.register(stdin, uselect.POLLIN)

def writeln(msg):
    # print() is the most reliable across MicroPython builds for USB CDC stdout.
    print(msg)

def read_line(timeout_ms=10000):
    start = time.ticks_ms()
    buf = b""
    while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
        b = stdin.read(1)
        if b:
            if b == b"\n":
                return buf.decode("utf-8", "replace").strip()
            buf += b
        else:
            time.sleep_ms(2)
    return None

writeln("READY")

def read_exact(n):
    # Read exactly n bytes with a timeout.
    remaining = n
    start = time.ticks_ms()
    timeout_ms = 120_000
    while remaining > 0:
        if time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
            raise RuntimeError("rx_timeout")
        # Don't call stdin.read(n) unless data is available; it can block forever.
        events = poller.poll(10)
        if not events:
            time.sleep_ms(1)
            continue

        want = 1024 if remaining > 1024 else remaining
        chunk = stdin.read(want)
        if not chunk:
            time.sleep_ms(1)
            continue
        remaining -= len(chunk)

while True:
    try:
        line = read_line(60000)
        if line is None:
            continue

        if line == "PING":
            writeln("PONG")
            continue

        if line.startswith("FRAME "):
            parts = line.split()
            # FRAME <w> <h> BWR2 <black_bytes> <red_bytes>
            if len(parts) != 6:
                writeln("ERR bad_header")
                continue

            _, w, h, fmt, n_black, n_red = parts
            if fmt != "BWR2":
                writeln("ERR bad_fmt")
                continue

            try:
                w = int(w)
                h = int(h)
                n_black = int(n_black)
                n_red = int(n_red)
            except Exception:
                writeln("ERR bad_len")
                continue

            # Validate expected payload sizes for packed 1bpp planes.
            expected = ((w + 7) // 8) * h
            if n_black != expected or n_red != expected:
                # Drain provided payload bytes to resync stream then error.
                read_exact(n_black + n_red)
                writeln("ERR bad_plane_len exp={} got_black={} got_red={}".format(expected, n_black, n_red))
                continue

            # Signal host that we're ready to receive payloads.
            writeln("RDY")

            # Consume payloads. Rendering will be implemented next.
            read_exact(n_black)
            read_exact(n_red)
            writeln("OK")
            continue

        # Unknown command
        writeln("ERR " + line)
    except Exception as exc:
        # Never crash to REPL; keep USB protocol stable.
        writeln("ERR exception {}".format(exc))
        time.sleep(0.2)