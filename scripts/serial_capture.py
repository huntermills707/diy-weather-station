"""Capture station serial output with host timestamps.

Usage:
    uv run --with pyserial scripts/serial_capture.py [--port /dev/ttyUSB0]
        [--send s] [--seconds 60] [--out capture.log]

Opening the port resets the ESP32 once (Linux raises DTR/RTS on open), so
cumulative counters restart from zero on every capture. Each
line is printed (and optionally written to --out) prefixed with the host's
UTC time. --send writes characters to the board after opening (e.g. "s" for
an immediate report, "c" to toggle the calibration stream).
"""

import argparse
import sys
import time
from datetime import UTC, datetime

import serial

BOOT_WAIT_S = 2.5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--send", default="", help="characters to send after opening")
    parser.add_argument("--seconds", type=float, default=0, help="stop after N s (0 = forever)")
    parser.add_argument("--out", help="also append lines to this file")
    args = parser.parse_args()

    port = serial.Serial()
    port.port = args.port
    port.baudrate = args.baud
    port.timeout = 0.5
    # Keep both auto-reset lines released, or the board can be held in reset.
    port.dtr = False
    port.rts = False
    port.open()

    if args.send:
        # Opening the port rebooted the board; bytes sent before setup()
        # finishes are lost, so wait for boot before sending.
        time.sleep(BOOT_WAIT_S)
        port.write(args.send.encode())

    out = open(args.out, "a") if args.out else None
    deadline = time.monotonic() + args.seconds if args.seconds else None
    try:
        while deadline is None or time.monotonic() < deadline:
            raw = port.readline()
            if not raw:
                continue
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            line = f"{stamp} {raw.decode(errors='replace').rstrip()}"
            print(line, flush=True)
            if out:
                out.write(line + "\n")
                out.flush()
    except KeyboardInterrupt:
        pass
    finally:
        port.close()
        if out:
            out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
