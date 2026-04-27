import sys
import time

stdin = sys.stdin.buffer
stdout = sys.stdout

def writeln(msg):
    # Avoid relying on flush(); write newline-terminated records.
    stdout.write(str(msg) + "\n")

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
    # Read exactly n bytes efficiently (no large allocations).
    remaining = n
    buf = bytearray(1024)
    mv = memoryview(buf)
    while remaining > 0:
        want = 1024 if remaining > 1024 else remaining
        got = stdin.readinto(mv[:want])
        if not got:
            time.sleep_ms(1)
            continue
        remaining -= got

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
                n_black = int(n_black)
                n_red = int(n_red)
            except Exception:
                writeln("ERR bad_len")
                continue

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