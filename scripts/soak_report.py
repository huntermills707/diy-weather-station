"""Summarize a soak test from the readings database (JAE-50).

Compares the readings stored in a time range against the five-minute cadence
(ADR 0001) and lists every anomaly with its timestamp: gaps, readings lost
in transit (missing sequence numbers), reboots, unsynced clocks, sensor
errors, and clock offset between station and server.

Usage (on the Pi; standard library only):
    python3 scripts/soak_report.py /var/lib/weather-station/weather.db \\
        --since 2026-10-03T00:00:00Z --hours 24
"""

import argparse
import sqlite3
import sys
from datetime import UTC, datetime, timedelta

CADENCE_S = 300
# A reading later than this after the previous one counts as a gap.
GAP_THRESHOLD_S = CADENCE_S * 1.5


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def fmt(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def when(row: sqlite3.Row) -> str:
    return fmt(parse_utc(row["received_at"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", help="path to weather.db")
    parser.add_argument("--since", help="UTC start, e.g. 2026-10-03T00:00:00Z (default: 24 h ago)")
    parser.add_argument("--hours", type=float, default=24, help="length of the window (24)")
    parser.add_argument("--station", default="station-1")
    args = parser.parse_args()

    end_default = datetime.now(UTC)
    start = parse_utc(args.since) if args.since else end_default - timedelta(hours=args.hours)
    end = start + timedelta(hours=args.hours)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM readings WHERE station_id = ? AND received_at >= ? AND received_at < ? "
        "ORDER BY received_at",
        (args.station, fmt(start), fmt(end)),
    ).fetchall()

    expected = int(args.hours * 3600 // CADENCE_S)
    print(f"Soak window {fmt(start)} .. {fmt(end)} ({args.hours:g} h), station {args.station}")
    print(f"Readings stored: {len(rows)} of {expected} expected ({len(rows) / expected:.1%})")
    if not rows:
        return 1

    anomalies: list[tuple[str, str]] = []

    # Gaps in arrival time (the server's clock, so this works even unsynced).
    times = [parse_utc(r["received_at"]) for r in rows]
    if (times[0] - start).total_seconds() > GAP_THRESHOLD_S:
        anomalies.append((fmt(start), f"no readings for {(times[0] - start)} after window start"))
    for prev, cur in zip(times, times[1:], strict=False):
        gap = (cur - prev).total_seconds()
        if gap > GAP_THRESHOLD_S:
            missing = round(gap / CADENCE_S) - 1
            note = f"gap of {gap / 60:.1f} min (~{missing} missing) until {fmt(cur)}"
            anomalies.append((fmt(prev), note))
    if (end - times[-1]).total_seconds() > GAP_THRESHOLD_S and end <= datetime.now(UTC):
        anomalies.append((fmt(times[-1]), "no readings after this until window end"))

    # Sequence numbers within each boot: a hole means the station took the
    # reading but it never reached the database.
    boots: dict[str, list[int]] = {}
    lost = 0
    for r in rows:
        boot, _, seq = r["reading_id"].partition("-")
        if boot not in boots:
            boots[boot] = []
            if len(boots) > 1:
                note = f"station rebooted (boot id {boot}, uptime {r['uptime_ms']} ms)"
                anomalies.append((when(r), note))
        if seq.isdigit():
            boots[boot].append(int(seq))
    for boot, seqs in boots.items():
        seen = set(seqs)
        holes = [n for n in range(min(seqs), max(seqs) + 1) if n not in seen]
        lost += len(holes)
        if holes:
            note = f"boot {boot}: {len(holes)} readings never stored, seq {holes}"
            anomalies.append(("(whole run)", note))

    unsynced = [r for r in rows if r["device_time"] is None]
    for r in unsynced:
        anomalies.append((when(r), f"{r['reading_id']}: station clock not NTP-synced"))
    for r in rows:
        if r["bme280"] != "ok":
            anomalies.append((when(r), f"{r['reading_id']}: bme280={r['bme280']}"))
        if r["wind_dir_deg"] is None:
            anomalies.append((when(r), f"{r['reading_id']}: wind vane unknown"))

    # Clock offset: server receive time minus station time. Includes upload
    # latency (normally well under a second).
    offsets = [
        (parse_utc(r["received_at"]) - parse_utc(r["device_time"])).total_seconds()
        for r in rows
        if r["device_time"] is not None
    ]

    print(f"Boots seen: {len(boots)}; readings lost in transit (seq holes): {lost}")
    print("Duplicates stored: 0 (enforced by UNIQUE (station_id, reading_id))")
    print(f"Unsynced readings: {len(unsynced)}")
    if offsets:
        offsets.sort()
        median = offsets[len(offsets) // 2]
        print(
            f"Receive minus device time: median {median:.1f} s, "
            f"min {offsets[0]:.1f} s, max {offsets[-1]:.1f} s"
        )
    rssi = [r["rssi_dbm"] for r in rows if r["rssi_dbm"] is not None]
    if rssi:
        print(f"RSSI: {min(rssi)} .. {max(rssi)} dBm")

    print(f"\nAnomalies ({len(anomalies)}):" if anomalies else "\nNo anomalies.")
    for stamp, what in sorted(anomalies):
        print(f"  {stamp:20}  {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
