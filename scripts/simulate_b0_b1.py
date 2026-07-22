#!/usr/bin/env python3
"""
simulate_b0_b1.py — B0 (flat) vs B1 (tri-shtresa + severity + dedup + flap-guard),
mbi TË NJËJTAT sinjale të papërpunuara (jo periudha të ndryshme kohore).

Lexon data-raw/l1_uptimekuma_important.csv, l3_pve_tasks.csv, l3_pbs_tasks.csv
(L2/InfluxDB do shtohet më vonë — shih README, TODO). Zbaton rregullin e vendimit
nga §3 e Paper4-Telemetry-Platform.md:

    classify(signal):
      layer    = L1 | L2 | L3
      severity = f(layer, magnitude, persistence)
      channel  = route(severity)
      suppress = dedup(signal, window) ∧ flap_guard(signal)

Përdorim:
  cd projects/research/Papers/paper4-alerting
  python3 scripts/simulate_b0_b1.py

Parametrat (FLAP_GUARD_SECONDS, DEDUP_WINDOW_*) janë eksplicitë me qëllim — janë
vendime metodologjike që duhen cituar te Paper 4 § Measurement Methodology, jo të
fshehura brenda kodit pa dokumentim.
"""
import csv
import datetime
import os
from collections import defaultdict

FLAP_GUARD_SECONDS = 60      # L1: cikël down->up nën këtë kohë = flap, s'njoftohet fare (as down as up)
DEDUP_WINDOW_CRITICAL = 60   # critical: praktikisht çdo sinjal njofton (evitohet vetëm retry i menjëhershëm)
DEDUP_WINDOW_INFO = 3600     # info: sinjale rutinë brenda 1h grupohen në një njoftim të vetëm (batch/digest)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data-raw")


def parse_iso(s):
    return datetime.datetime.fromisoformat(s.strip())


def load_l1(path):
    events = []
    with open(path) as f:
        for row in csv.DictReader(f):
            if row["note"] != "real_incident":
                continue  # përjashto setup_first_check_exclude / synthetic_test_monitor_exclude
            events.append({
                "time": parse_iso(row["time"]),
                "layer": "L1",
                "source": row["monitor"],
                "kind": "down" if row["status"] == "0" else "up",
            })
    return events


def load_l3(path, type_col):
    events = []
    with open(path) as f:
        for row in csv.DictReader(f):
            kind = "ok" if row["status"] == "OK" else "fail"
            events.append({
                "time": parse_iso(row["time"]),
                "layer": "L3",
                "source": f"{row['host']}:{row[type_col]}",
                "kind": kind,
            })
    return events


def severity_of(ev):
    if ev["layer"] == "L1":
        return "critical" if ev["kind"] == "down" else "info"
    if ev["layer"] == "L3":
        return "critical" if ev["kind"] == "fail" else "info"
    raise ValueError(f"layer i panjohur: {ev['layer']}")


def simulate_b0(events):
    """Flat: çdo sinjal -> 1 njoftim, pa dedup, pa flap-guard, pa dallim severity."""
    return len(events)


def apply_flap_guard(events):
    """Heq çiftet L1 down->up (të njëjtin burim) nën FLAP_GUARD_SECONDS — as down as up s'njoftohen."""
    by_source = defaultdict(list)
    for ev in events:
        if ev["layer"] == "L1":
            by_source[ev["source"]].append(ev)
    suppressed = set()
    for source, evs in by_source.items():
        evs.sort(key=lambda e: e["time"])
        for a, b in zip(evs, evs[1:]):
            if a["kind"] == "down" and b["kind"] == "up":
                if (b["time"] - a["time"]).total_seconds() < FLAP_GUARD_SECONDS:
                    suppressed.add(id(a))
                    suppressed.add(id(b))
    return [ev for ev in events if id(ev) not in suppressed]


def apply_dedup(events):
    """Grupon sinjale me (layer, severity, kategori burimi) brenda dritares — vetëm i pari njofton.
    Për L3, kategoria e burimit është lloji i task-ut (p.sh. 'backup'), jo VM/CT specifik — kështu
    B1 modelon një njoftim përmbledhës ("N backup-e OK") në vend të një-për-VM."""
    events = sorted(events, key=lambda e: e["time"])
    last_notified = {}
    notified = []
    for ev in events:
        sev = severity_of(ev)
        window = DEDUP_WINDOW_CRITICAL if sev == "critical" else DEDUP_WINDOW_INFO
        if ev["layer"] == "L3":
            source_category = ev["source"].split(":")[1] if ":" in ev["source"] else ev["source"]
        else:
            source_category = ev["source"]
        key = (ev["layer"], sev, source_category)
        last = last_notified.get(key)
        if last is None or (ev["time"] - last).total_seconds() > window:
            notified.append(ev)
            last_notified[key] = ev["time"]
    return notified


def simulate_b1(events):
    events = apply_flap_guard(events)
    notified = apply_dedup(events)
    return len(notified), notified


def load_l2_summary(path):
    """L2 (InfluxDB threshold crossings) — nxjerrë NGA InfluxDB drejtpërdrejt (influx CLI, CT104,
    17 Korrik 2026), jo nga eventet e papërpunuara si L1/L3. Për secilën rregull Grafana (CPU>0.8/1m,
    Disk>85/5m, RAM>90/5m, Temp>60/5m) llogaritëm në InfluxDB (Flux reduce()):
      n_samples = numri i vlerësimeve (aggregateWindow në rezolucionin e 'for')
      n_above   = sa prej tyre ishin mbi prag
      n_episodes = sa herë ndodhi kalimi nën->mbi prag (fillimi i një episodi)
    Kjo është më e trashë (aggregate, jo per-event) sesa L1/L3, ndaj:
      B0_L2 = n_above (çdo cikël vlerësimi mbi prag do të njoftonte, sikur B0 pa gjendje/debounce)
      B1_L2 = 2 * n_episodes (Grafana njofton 1x kur fillon 'Firing' + 1x kur kthehet 'Resolved';
              supozon çdo episod mbyllet brenda dritares — arsyetim i dokumentuar, jo matje direkte).
    """
    b0_l2 = 0
    b1_l2 = 0
    n_rules_triggered = 0
    with open(path) as f:
        for row in csv.DictReader(f):
            n_above = int(row["n_above"])
            n_episodes = int(row["n_episodes"])
            b0_l2 += n_above
            b1_l2 += 2 * n_episodes
            if n_episodes > 0:
                n_rules_triggered += 1
    return b0_l2, b1_l2, n_rules_triggered


def main():
    l1 = load_l1(os.path.join(DATA_DIR, "l1_uptimekuma_important.csv"))
    l3_pve = load_l3(os.path.join(DATA_DIR, "l3_pve_tasks.csv"), "type")
    l3_pbs = load_l3(os.path.join(DATA_DIR, "l3_pbs_tasks.csv"), "worker_type")
    all_events = l1 + l3_pve + l3_pbs

    print(f"Dritarja: 27 Qershor - 17 Korrik 2026 (~20 ditë)")
    print(f"Sinjale L1+L3 (per-event): {len(all_events)}")
    print(f"  L1 (Uptime Kuma, incidente reale): {len(l1)}")
    print(f"  L3 pve1 (tasks): {len(l3_pve)}")
    print(f"  L3 pbs (tasks): {len(l3_pbs)}")

    b0_l1l3 = simulate_b0(all_events)
    b1_l1l3_count, b1_events = simulate_b1(all_events)

    l2_path = os.path.join(DATA_DIR, "l2_influx_thresholds_summary.csv")
    b0_l2, b1_l2, n_rules_triggered = load_l2_summary(l2_path)
    print(f"L2 (InfluxDB threshold, aggregate): {b0_l2} mostra mbi prag, {n_rules_triggered} rregulla u aktivizuan")

    b0 = b0_l1l3 + b0_l2
    b1 = b1_l1l3_count + b1_l2
    reduction = (1 - b1 / b0) * 100 if b0 else 0

    print()
    print(f"B0 (flat, pa dedup/flap-guard/state):             {b0} njoftime  (L1+L3: {b0_l1l3} + L2: {b0_l2})")
    print(f"B1 (tri-shtresa + severity + dedup + flap-guard): {b1} njoftime  (L1+L3: {b1_l1l3_count} + L2: {b1_l2})")
    print(f"Reduktim i njoftimeve:                            {reduction:.1f}%")

    critical_in = [e for e in all_events if severity_of(e) == "critical"]
    critical_out = [e for e in b1_events if severity_of(e) == "critical"]
    print()
    print(f"Sinjale 'critical' në hyrje (L1+L3): {len(critical_in)}")
    print(f"Sinjale 'critical' që arritën notifikim te B1 (L1+L3): {len(critical_out)}")
    print(f"L2: {n_rules_triggered} rregulla u aktivizuan gjatë dritares — të gjitha modelohen si të njoftuara te B1 (start+resolve), pra zero FN by construction.")
    if len(critical_out) < len(critical_in):
        print("  ⚠️  disa 'critical' L1/L3 u suprimuan (flap-guard ose dedup) — kontrollo nëse janë FN")
        print("      apo suprimim i arsyeshëm (p.sh. flap i vërtetë). Detajet:")
        suppressed_ids = {id(e) for e in critical_in} - {id(e) for e in critical_out}
        for e in critical_in:
            if id(e) in suppressed_ids:
                print(f"      - {e['time']} {e['layer']} {e['source']} {e['kind']}")
    else:
        print("  ✅ zero FN (L1/L3) — çdo sinjal critical i papërpunuar arriti notifikim edhe te B1.")


if __name__ == "__main__":
    main()
