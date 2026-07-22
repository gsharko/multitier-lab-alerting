#!/usr/bin/env python3
"""
b0_counter.py — Paper 4, live sequential B0 run (i KTHYESHËM, JO shkatërrues).

NUK ndryshon konfigurimin live të alarmimit (ntfy/Grafana/PVE mbeten B1 të paprekur).
Në vend të kësaj, taps READ-ONLY te të tri burimet (L1/L2/L3), dhe për çdo cikël numëron:
  - B0: sa njoftime do dërgonte një sistem FLAT (çdo sinjal → 1 njoftim)
  - B1: sa do dërgonte modeli tri-shtresor (severity + dedup + flap-guard)
dhe i shkruan të dy numrat te InfluxDB (measurement `b0_shadow`, fields b0/b1, tag source).

Kështu, gjatë periudhës live (2-4 javë), Grafana tregon dy vija kumulative (B0 vs B1) mbi
sinjale REALE forward-looking — validim live i simulimit historik (1406→227), pa kosto
alarm-fatigue në telefon dhe pa rrezikun e çmontimit/rimontimit të konfigurimit B1.

I kthyeshëm plotësisht: `systemctl stop b0-counter` → gjithçka ndalon, asgjë s'mbetet e ndryshuar.

--- Burimet (të gjitha read-only) ---
  L2 (InfluxDB threshold): LOKAL te CT104 — evaluon 4 rregullat Grafana (CPU>0.8, Disk>85,
      RAM>90, Temp>60) mbi dritaren e ciklit; B0 += mostra mbi prag, B1 += episode (start).
  L1 (Uptime Kuma): SSH te CT107 (DL360), lexon heartbeat.db (important=1) të reja në dritare.
  L3 (PVE/PBS tasks): SSH te pve1/PBS, numëron task-et e reja (OK=info, fail=critical).

L1/L3 kërkojnë çelës SSH nga CT104 te hostet përkatës. Nëse një burim s'arrihet, cikli e kapërcen
atë burim (degradim i qetë), nuk rrëzohet.

Konfigurimi merret nga /etc/b0-counter/env (shih b0-counter.env.template).
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# ---- Konfigurim nga env ----
INFLUX_URL = os.environ.get("INFLUX_URL", "http://localhost:8086")
INFLUX_ORG = os.environ.get("INFLUX_ORG", "fie")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "lab")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN", "")
INTERVAL_S = int(os.environ.get("B0_INTERVAL_S", "3600"))  # një cikël në orë (default)

# Burimet remote (SSH). Bosh => burimi kapërcehet.
UPTIME_KUMA_SSH = os.environ.get("UPTIME_KUMA_SSH", "")   # p.sh. root@192.168.20.24
UPTIME_KUMA_DB = os.environ.get("UPTIME_KUMA_DB", "/app/data/kuma.db")
PVE_SSH = os.environ.get("PVE_SSH", "")                   # p.sh. root@192.168.20.10
PBS_SSH = os.environ.get("PBS_SSH", "")                   # p.sh. root@192.168.20.30

# Pragjet e 4 rregullave Grafana (nxjerrë 17 Korrik 2026 nga API-ja e provisioning-ut).
# "simple" = krahasim i drejtpërdrejtë fushe; "pivot" = kërkon used/avail ose memused/memtotal.
L2_RULES_SIMPLE = [
    {"name": "cpu", "flux_filter": 'r._measurement == "cpustat" and r._field == "cpu"',
     "threshold": 0.8, "agg": "1m"},
    {"name": "temp", "flux_filter": 'r._measurement == "sensors" and r._field == "temp_input" and r.chip =~ /coretemp/',
     "threshold": 60.0, "agg": "5m"},
]
L2_RULES_PIVOT = [
    {"name": "disk", "measurement": "system", "a": "used", "b": "avail",
     "expr": "100.0 * float(v: r.used) / (float(v: r.avail) + float(v: r.used))",
     "rowkey": '["_time","host","nodename"]', "threshold": 85.0, "agg": "5m"},
    {"name": "ram", "measurement": "memory", "a": "memused", "b": "memtotal",
     "expr": "100.0 * float(v: r.memused) / float(v: r.memtotal)",
     "rowkey": '["_time","host"]', "threshold": 90.0, "agg": "5m"},
]

DEDUP_WINDOW_CRITICAL = 60
DEDUP_WINDOW_INFO = 3600

STATE_FILE = os.environ.get("B0_STATE_FILE", "/var/lib/b0-counter/state.json")


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


def influx_query(flux, timeout=15):
    endpoint = f"{INFLUX_URL.rstrip('/')}/api/v2/query?org={urllib.parse.quote(INFLUX_ORG)}"
    req = urllib.request.Request(
        endpoint, data=flux.encode(),
        headers={
            "Authorization": f"Token {INFLUX_TOKEN}",
            "Content-Type": "application/vnd.flux",
            "Accept": "application/csv",
        }, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode()


def influx_write(lines, timeout=10):
    endpoint = (f"{INFLUX_URL.rstrip('/')}/api/v2/write?org={urllib.parse.quote(INFLUX_ORG)}"
                f"&bucket={urllib.parse.quote(INFLUX_BUCKET)}&precision=s")
    data = "\n".join(lines).encode()
    req = urllib.request.Request(
        endpoint, data=data,
        headers={"Authorization": f"Token {INFLUX_TOKEN}",
                 "Content-Type": "text/plain; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"write status {resp.status}")


def _parse_reduce_value(csv_text, colname):
    """Nxjerr një vlerë të vetme numerike nga output i reduktimit Flux."""
    lines = [ln for ln in csv_text.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 2:
        return 0
    header = lines[0].split(",")
    if colname not in header:
        return 0
    idx = header.index(colname)
    total = 0
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) > idx and parts[idx]:
            try:
                total += int(float(parts[idx]))
            except ValueError:
                pass
    return total


_REDUCE_TAIL = '''  |> group()
  |> sort(columns: ["_time"])
  |> reduce(
      identity: {n_above: 0, n_trans: 0, prev: 0},
      fn: (r, accumulator) => ({
        n_above: accumulator.n_above + r.above,
        n_trans: accumulator.n_trans + (if r.above == 1 and accumulator.prev == 0 then 1 else 0),
        prev: r.above
      })
    )
'''


def count_l2(since_rfc3339, until_rfc3339):
    """B0 (mostra mbi prag) + B1 (episode×2, Firing+Resolved) për të 4 rregullat L2 lokale."""
    b0 = 0
    episodes = 0
    for rule in L2_RULES_SIMPLE:
        flux = (f'from(bucket: "{INFLUX_BUCKET}")\n'
                f'  |> range(start: {since_rfc3339}, stop: {until_rfc3339})\n'
                f'  |> filter(fn: (r) => {rule["flux_filter"]})\n'
                f'  |> aggregateWindow(every: {rule["agg"]}, fn: mean, createEmpty: false)\n'
                f'  |> map(fn: (r) => ({{ r with above: if r._value > {rule["threshold"]} then 1 else 0 }}))\n'
                + _REDUCE_TAIL)
        try:
            csv_text = influx_query(flux)
        except Exception as e:
            log(f"L2 rule {rule['name']} query dështoi: {e}")
            continue
        b0 += _parse_reduce_value(csv_text, "n_above")
        episodes += _parse_reduce_value(csv_text, "n_trans")

    for rule in L2_RULES_PIVOT:
        flux = (f'from(bucket: "{INFLUX_BUCKET}")\n'
                f'  |> range(start: {since_rfc3339}, stop: {until_rfc3339})\n'
                f'  |> filter(fn: (r) => r._measurement == "{rule["measurement"]}")\n'
                f'  |> filter(fn: (r) => r._field == "{rule["a"]}" or r._field == "{rule["b"]}")\n'
                f'  |> aggregateWindow(every: {rule["agg"]}, fn: mean, createEmpty: false)\n'
                f'  |> pivot(rowKey:{rule["rowkey"]}, columnKey: ["_field"], valueColumn: "_value")\n'
                f'  |> map(fn: (r) => ({{ r with pct: {rule["expr"]} }}))\n'
                f'  |> map(fn: (r) => ({{ r with above: if r.pct > {rule["threshold"]} then 1 else 0 }}))\n'
                + _REDUCE_TAIL)
        try:
            csv_text = influx_query(flux)
        except Exception as e:
            log(f"L2 rule {rule['name']} query dështoi: {e}")
            continue
        b0 += _parse_reduce_value(csv_text, "n_above")
        episodes += _parse_reduce_value(csv_text, "n_trans")

    b1 = episodes * 2  # çdo episod = Firing + Resolved
    return b0, b1


def ssh_run(target, remote_cmd, timeout=20):
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, remote_cmd],
        capture_output=True, text=True, timeout=timeout,
    )


def count_l1(since_unix_ms, until_unix_ms):
    """Uptime Kuma heartbeat important=1 të reja në dritare (SSH sqlite). B0=çdo event, B1=me flap-guard."""
    if not UPTIME_KUMA_SSH:
        return 0, 0
    # important events me kohën (ms) dhe status; përjashtojmë synthetic/setup s'ka si t'i dimë live,
    # ndaj numërojmë çdo important real (setup s'ndodh më pas ditës së parë).
    q = (f"SELECT time,status FROM heartbeat WHERE important=1 "
         f"AND time > datetime({since_unix_ms // 1000},'unixepoch') "
         f"AND time <= datetime({until_unix_ms // 1000},'unixepoch') ORDER BY time;")
    cmd = f"sqlite3 {UPTIME_KUMA_DB} \"{q}\""
    try:
        r = ssh_run(UPTIME_KUMA_SSH, cmd)
    except Exception as e:
        log(f"L1 SSH dështoi: {e}")
        return 0, 0
    if r.returncode != 0:
        log(f"L1 sqlite dështoi: {r.stderr.strip()}")
        return 0, 0
    rows = [ln for ln in r.stdout.splitlines() if ln.strip()]
    b0 = len(rows)  # flat: çdo ndryshim statusi = 1 njoftim
    # B1: flap-guard heq çiftet down->up shumë të shpejta; live thjeshtojmë duke numëruar çdo
    # ngjarje (down ose up) por dedup brenda 60s për të njëjtin monitor s'modelohet dot pa gjendje
    # ndër-cikle të pasur — pra B1_L1 ≈ B0_L1 minus flap-e (të rralla). Konservativisht B1_L1=B0_L1.
    b1 = b0
    return b0, b1


def _tasks_b0_b1(tasks, type_key, since_unix, until_unix):
    """tasks: listë dict-esh me çelës kohe 'starttime' (unix), 'status', dhe type_key.
    B0 = çdo task i përfunduar në dritare. B1 = (kategori distinkte OK, dedup ~1 cikël) + (çdo dështim)."""
    ok_types = set()
    fails = 0
    b0 = 0
    for t in tasks:
        st = t.get("starttime")
        if st is None or not (since_unix < st <= until_unix):
            continue
        status = str(t.get("status", ""))
        b0 += 1
        if status == "OK":
            ok_types.add(t.get(type_key, "?"))
        else:
            fails += 1  # çdo status jo-OK = critical
    b1 = len(ok_types) + fails  # info: 1 njoftim/kategori/cikël; critical: çdo dështim
    return b0, b1


def count_l3(since_unix, until_unix):
    """PVE + PBS task-e të përfunduara në dritare (SSH, read-only). Kthen (b0, b1)."""
    total_b0 = 0
    total_b1 = 0
    if PVE_SSH:
        cmd = "pvesh get /nodes/$(hostname)/tasks --output-format json 2>/dev/null"
        try:
            r = ssh_run(PVE_SSH, cmd)
            if r.returncode == 0 and r.stdout.strip():
                tasks = json.loads(r.stdout)
                # pvesh: starttime (unix int), type, status ('OK' ose string gabimi)
                b0, b1 = _tasks_b0_b1(tasks, "type", since_unix, until_unix)
                total_b0 += b0
                total_b1 += b1
        except Exception as e:
            log(f"L3 PVE dështoi: {e}")
    if PBS_SSH:
        cmd = "proxmox-backup-manager task list --all --output-format json 2>/dev/null"
        try:
            r = ssh_run(PBS_SSH, cmd)
            if r.returncode == 0 and r.stdout.strip():
                tasks = json.loads(r.stdout)
                # PBS: starttime (unix), worker_type/worker-type, status
                for t in tasks:
                    if "worker-type" in t and "worker_type" not in t:
                        t["worker_type"] = t["worker-type"]
                b0, b1 = _tasks_b0_b1(tasks, "worker_type", since_unix, until_unix)
                total_b0 += b0
                total_b1 += b1
        except Exception as e:
            log(f"L3 PBS dështoi: {e}")
    return total_b0, total_b1


def cycle():
    now = int(time.time())
    state = load_state()
    since = state.get("last_ts", now - INTERVAL_S)
    until = now

    since_rfc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))
    until_rfc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(until))

    b0_l2, b1_l2 = count_l2(since_rfc, until_rfc)
    b0_l1, b1_l1 = count_l1(since * 1000, until * 1000)
    b0_l3, b1_l3 = count_l3(since, until)

    b0_total = b0_l2 + b0_l1 + b0_l3
    b1_total = b1_l2 + b1_l1 + b1_l3

    lines = [
        f"b0_shadow,source=L2 b0={b0_l2}i,b1={b1_l2}i {until}",
        f"b0_shadow,source=L1 b0={b0_l1}i,b1={b1_l1}i {until}",
        f"b0_shadow,source=L3 b0={b0_l3}i,b1={b1_l3}i {until}",
        f"b0_shadow,source=total b0={b0_total}i,b1={b1_total}i {until}",
    ]
    try:
        influx_write(lines)
        log(f"cikli OK: B0={b0_total} (L2={b0_l2} L1={b0_l1} L3={b0_l3}) | B1={b1_total}")
        state["last_ts"] = until
        save_state(state)
    except Exception as e:
        log(f"write InfluxDB dështoi, watermark s'u përparua: {e}")


def main():
    if not INFLUX_TOKEN:
        log("GABIM: INFLUX_TOKEN bosh — vendos /etc/b0-counter/env")
        sys.exit(1)
    log(f"b0-counter nis (interval={INTERVAL_S}s, bucket={INFLUX_BUCKET})")
    while True:
        try:
            cycle()
        except Exception as e:
            log(f"cikli dështoi papritur: {e}")
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
