import sys
import time

stdin = sys.stdin.buffer
stdout = sys.stdout

def writeln(msg):
    # Some MicroPython builds expose stdout without flush().
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

while True:
    line = read_line(60000)
    if line is None:
        continue
    if line == "PING":
        writeln("PONG")
    else:
        writeln("ERR " + line)