import os
#!/usr/bin/env python3
"""
latency_ntfy_dispatch.py — Paper 4 §5, matje latence "event -> dispatch njoftimi"
(trigger -> ntfy server ack). MAT VETËM deri te serveri ntfy (jo push-in real
te telefoni — ai hap s'është i matshëm nga lab-i pa instrumentim në telefon;
shënohet si kufizim i dokumentuar, jo si numër i supozuar).

Kërkon: akses te ntfy (http://192.168.20.25), curl.

Përdorim:
  python3 latency_ntfy_dispatch.py --n 30 --interval 3
"""
import argparse
import json
import subprocess
import sys
import time

NTFY_URL = "http://192.168.20.25/critical"
NTFY_USER = "genci"
NTFY_PASS = os.environ.get("NTFY_PASS", "")  # vendos lokalisht ose env; shih CREDENTIALS.local.md


def send_one(seq: int, timeout: float = 10.0):
    t0 = time.time()
    result = subprocess.run(
        [
            "curl", "-s", "-u", f"{NTFY_USER}:{NTFY_PASS}",
            "-H", "Priority: urgent",
            "-H", f"Title: latency-test-{seq}",
            "-d", f"latency probe seq={seq}",
            NTFY_URL,
        ],
        capture_output=True, text=True, timeout=timeout,
    )
    t1 = time.time()
    rtt = t1 - t0
    server_time = None
    try:
        resp = json.loads(result.stdout)
        server_time = resp.get("time")
    except (json.JSONDecodeError, ValueError):
        pass
    return rtt, server_time


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
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--interval", type=float, default=3.0)
    args = ap.parse_args()

    base_seq = int(time.time())
    rtts = []
    print("seq,rtt_ms,server_time", file=sys.stderr)
    for i in range(args.n):
        seq = base_seq + i
        rtt, server_time = send_one(seq)
        rtts.append(rtt)
        print(f"{seq},{rtt*1000:.0f},{server_time}", file=sys.stderr)
        time.sleep(args.interval)

    print()
    print(f"Mostra: {args.n}")
    print(f"p50: {percentile(rtts, 0.50)*1000:.0f} ms")
    print(f"p95: {percentile(rtts, 0.95)*1000:.0f} ms")
    print(f"p99: {percentile(rtts, 0.99)*1000:.0f} ms")
    print(f"max: {max(rtts)*1000:.0f} ms")
    print(f"min: {min(rtts)*1000:.0f} ms")
    print()
    print("SHENIM: kjo mat vetem trigger->ntfy-server-ack, JO dorezimin real te telefoni")
    print("(ai hap kerkon Tailscale/FCM-alternativ dhe s'eshte i matshem nga lab-i pa instrumentim ne telefon).")


if __name__ == "__main__":
    main()
