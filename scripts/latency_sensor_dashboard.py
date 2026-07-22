import os
#!/usr/bin/env python3
"""
latency_sensor_dashboard.py — Paper 4 §5, matje latence "sensor -> dashboard"
(MQTT publish -> InfluxDB queryable), mbi topic dedikuar teste "lab/test/latency"
(s'përzihet me të dhëna reale të nyjeve).

Xhirohet BRENDA CT104 (telemetry) — Mosquitto + InfluxDB janë lokale, s'ka nevojë
për rrjet të jashtëm. Kërkon: mosquitto-clients (mosquitto_pub), influx CLI.

Metodologjia: për çdo mostër, publikohet një mesazh MQTT me një `seq` unik;
regjistrohet timestamp-i i publikimit (T_pub); pastaj bëhet poll periodik te
InfluxDB derisa pika me atë `seq` të shfaqet (T_seen). latency = T_seen - T_pub.
Kjo mat gjithë rrugëtimin real: Mosquitto -> Telegraf -> InfluxDB write -> queryable.

Përdorim:
  python3 latency_sensor_dashboard.py --n 30 --token "$TOKEN" --interval 3

Output: CSV te stdout (seq,latency_ms) + përmbledhje p50/p95/p99/max në fund.
"""
import argparse
import csv
import io
import subprocess
import sys
import time

MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_USER = "lab"
MQTT_PASS = os.environ.get("MQTT_PASS", "")  # vendos lokalisht ose env; shih CREDENTIALS.local.md
TEST_TOPIC = "lab/test/latency"

INFLUX_ORG = "fie"
INFLUX_HOST = "http://localhost:8086"
INFLUX_BUCKET = "lab"


def publish(seq: int) -> None:
    subprocess.run(
        [
            "mosquitto_pub", "-h", MQTT_HOST, "-p", str(MQTT_PORT),
            "-u", MQTT_USER, "-P", MQTT_PASS,
            "-t", TEST_TOPIC, "-m", f'{{"seq":{seq}}}',
        ],
        check=True,
        capture_output=True,
    )


def seq_is_visible(token: str, seq: int, lookback_s: int = 60) -> bool:
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -{lookback_s}s)
  |> filter(fn: (r) => r._measurement == "mqtt_consumer" and r.topic == "{TEST_TOPIC}")
  |> filter(fn: (r) => r._field == "seq" and r._value == {float(seq)})
'''
    result = subprocess.run(
        ["influx", "query", flux, "--org", INFLUX_ORG, "--token", token,
         "--host", INFLUX_HOST, "--raw"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False
    # Parse annotated CSV (skip lines starting with '#'); find _value column.
    lines = [ln for ln in result.stdout.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 2:
        return False
    reader = csv.reader(io.StringIO("\n".join(lines)))
    header = next(reader, None)
    if header is None or "_value" not in header:
        return False
    idx = header.index("_value")
    for row in reader:
        if len(row) > idx:
            try:
                if float(row[idx]) == float(seq):
                    return True
            except ValueError:
                continue
    return False


def measure_one(seq: int, token: str, poll_interval: float, timeout: float):
    t_pub = time.time()
    publish(seq)
    deadline = t_pub + timeout
    while time.time() < deadline:
        if seq_is_visible(token, seq):
            return time.time() - t_pub
        time.sleep(poll_interval)
    return None


def percentile(data, p):
    if not data:
        return None
    data = sorted(data)
    k = (len(data) - 1) * p
    f, c = int(k), min(int(k) + 1, len(data) - 1)
    if f == c:
        return data[f]
    return data[f] + (data[c] - data[f]) * (k - f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="numri i mostrave")
    ap.add_argument("--token", required=True, help="InfluxDB token")
    ap.add_argument("--interval", type=float, default=3.0, help="pauzë midis mostrave (s)")
    ap.add_argument("--poll-interval", type=float, default=0.2, help="frekuenca e poll-it (s)")
    ap.add_argument("--timeout", type=float, default=20.0, help="timeout per mostër (s)")
    args = ap.parse_args()

    base_seq = int(time.time())  # unik për këtë run, shmang kolizion me testet e mëparshme
    latencies = []
    timeouts = 0

    print("seq,latency_ms", file=sys.stderr)
    for i in range(args.n):
        seq = base_seq + i
        lat = measure_one(seq, args.token, args.poll_interval, args.timeout)
        if lat is None:
            timeouts += 1
            print(f"{seq},TIMEOUT", file=sys.stderr)
        else:
            latencies.append(lat)
            print(f"{seq},{lat*1000:.0f}", file=sys.stderr)
        time.sleep(args.interval)

    print()
    print(f"Mostra: {args.n} | suksesshme: {len(latencies)} | timeout: {timeouts}")
    if latencies:
        print(f"p50: {percentile(latencies, 0.50)*1000:.0f} ms")
        print(f"p95: {percentile(latencies, 0.95)*1000:.0f} ms")
        print(f"p99: {percentile(latencies, 0.99)*1000:.0f} ms")
        print(f"max: {max(latencies)*1000:.0f} ms")
        print(f"min: {min(latencies)*1000:.0f} ms")


if __name__ == "__main__":
    main()
