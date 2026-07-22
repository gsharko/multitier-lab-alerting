#!/usr/bin/env python3
"""
loadtest_mqtt.py — Paper 4 §5, load test MQTT (throughput, pika e humbjes).

Metodologjia: për çdo madhësi burst-i (N mesazhe), publikohen shpejt (mosquitto_pub -l,
një lidhje e vetme, jo një proces i ri për mesazh) te topic dedikuar "lab/test/loadtest".
Çdo mesazh ka një `seq` unik brenda një range-i të rezervuar për atë burst (s'përplaset
me burste të tjera). Pas një pauze (të mjaftueshme për flush_interval të Telegraf-it),
numërohen sa `seq` distinkte mbërritën në InfluxDB → % humbje = 1 - (arritur/dërguar).

Raporton edhe kohën reale të publikimit (burst_size / publish_duration = achieved rate),
pra throughput-in aktual të arritshëm nga ky klient — jo domosdoshmërisht kufiri i
brokerit/Telegraf, por një matje e ndershme e asaj që u vërtetua.

Kërkon: mosquitto-clients (mosquitto_pub), influx CLI. Xhirohet brenda CT104 (lokal).

Përdorim:
  python3 loadtest_mqtt.py --token "$TOKEN" --sizes 100 500 1000 2000 5000
"""
import argparse
import csv
import io
import os
import subprocess
import sys
import time

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_USER = "lab"
MQTT_PASS = os.environ.get("MQTT_PASS", "")  # vendos lokalisht ose env — kurrë hardcoded (shih CREDENTIALS.local.md)
TEST_TOPIC = "lab/test/loadtest"

INFLUX_ORG = "fie"
INFLUX_HOST = "http://localhost:8086"
INFLUX_BUCKET = "lab"


def publish_burst(seq_start: int, n: int) -> float:
    """Publikon n mesazhe (seq_start..seq_start+n-1) përmes një lidhjeje të vetme
    (mosquitto_pub -l, stdin). Kthen kohëzgjatjen e publikimit (s)."""
    lines = "\n".join(f'{{"seq":{seq_start + i}}}' for i in range(n))
    t0 = time.time()
    subprocess.run(
        [
            "mosquitto_pub", "-h", MQTT_HOST, "-p", str(MQTT_PORT),
            "-u", MQTT_USER, "-P", MQTT_PASS,
            "-t", TEST_TOPIC, "-l",
        ],
        input=lines, text=True, check=True, capture_output=True,
    )
    return time.time() - t0


def count_landed(token: str, seq_start: int, seq_end: int, lookback_s: int = 120) -> int:
    """Numëron sa `seq` distinktë (brenda [seq_start, seq_end)) u shkruan në InfluxDB."""
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{lookback_s}s)
  |> filter(fn: (r) => r._measurement == "mqtt_consumer" and r.topic == "{TEST_TOPIC}")
  |> filter(fn: (r) => r._field == "seq" and r._value >= {float(seq_start)} and r._value < {float(seq_end)})
  |> count()
'''
    result = subprocess.run(
        ["influx", "query", flux, "--org", INFLUX_ORG, "--token", token,
         "--host", INFLUX_HOST, "--raw"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return -1
    lines = [ln for ln in result.stdout.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 2:
        return 0
    reader = csv.reader(io.StringIO("\n".join(lines)))
    header = next(reader, None)
    if header is None or "_value" not in header:
        return 0
    idx = header.index("_value")
    total = 0
    for row in reader:
        if len(row) > idx:
            try:
                total += int(float(row[idx]))
            except ValueError:
                continue
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 500, 1000, 2000, 5000])
    ap.add_argument("--wait-after", type=float, default=15.0, help="pauzë para se të numërohet (s)")
    ap.add_argument("--gap-between", type=float, default=5.0, help="pauzë midis burst-eve (s)")
    args = ap.parse_args()

    if not MQTT_PASS:
        print("[err] mungon MQTT_PASS (env). Vendose lokalisht — shih CREDENTIALS.local.md.", file=sys.stderr)
        sys.exit(1)

    seq_cursor = int(time.time()) * 100  # baze unike, hapësirë e mjaftueshme midis burst-eve
    print(f"{'burst_size':>10} {'publish_s':>10} {'rate_msg_s':>11} {'landed':>8} {'loss_pct':>9}")
    results = []
    for n in args.sizes:
        seq_start = seq_cursor
        seq_end = seq_cursor + n
        dur = publish_burst(seq_start, n)
        rate = n / dur if dur > 0 else float("inf")
        time.sleep(args.wait_after)
        landed = count_landed(args.token, seq_start, seq_end)
        loss_pct = (1 - landed / n) * 100 if n else 0
        print(f"{n:>10} {dur:>10.2f} {rate:>11.1f} {landed:>8} {loss_pct:>8.1f}%")
        results.append((n, dur, rate, landed, loss_pct))
        seq_cursor = seq_end + 100000  # hapësirë e sigurt para burst-it tjetër
        time.sleep(args.gap_between)

    print()
    print("Përmbledhje CSV (burst_size,publish_s,rate_msg_s,landed,loss_pct):")
    for row in results:
        print(f"{row[0]},{row[1]:.2f},{row[2]:.1f},{row[3]},{row[4]:.1f}")


if __name__ == "__main__":
    main()
