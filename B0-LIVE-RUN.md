# Live sequential B0 run — runbook (Paper 4, Task #12)

> **✅ LIVE që nga 18 Korrik 2026** — shërbimi `b0-counter.service` është `active` te CT104
> (telemetry, 192.168.20.11). Numëron çdo orë. Smoke test i validuar: L3 ktheu 19 task / 6h (B0=19, B1=3).
> Të dhënat e testit u fshinë; seria live nisi e pastër nga 18 Korrik. Lëre 2-4 javë, pastaj krahaso
> `b0_total/b1_total` me -83.9% të simulimit historik.

**Qëllimi:** validim LIVE forward-looking i simulimit historik (1406→227, -83.9%). Një shërbim
(`b0_counter.py`) numëron në kohë reale sa njoftime do dërgonte **B0** (flat) vs **B1** (tri-shtresor)
nga të njëjtat sinjale reale, dhe i shkruan te InfluxDB (`b0_shadow`). Grafana pastaj tregon dy vija
kumulative gjatë 2-4 javëve.

**Deploy i kryer (18 Korrik):** çelësa SSH ed25519 nga CT104 → CT107/pve1/PBS; `sqlite3` u instalua te
CT107; `UPTIME_KUMA_DB=/var/lib/docker/volumes/uptime-kuma/_data/kuma.db` (volume Docker, jo path-i i
kontejnerit). Shërbimi live me interval 3600s.

## Pse ky dizajn (dhe jo "fik B1, kalo në flat")

Fikja e B1-it dhe kalimi i alarmimit real në flat për javë të tëra do të (a) të spamonte telefonin me
qindra njoftime, dhe (b) kërkonte çmontim + rimontim të `notifications.cfg` — pikërisht skedari që shkaktoi
incidentin e 13 Korrikut (parser fragil, rreshta bosh, config privat). **Ky dizajn s'prek fare B1-in.**
Është tap READ-ONLY: lexon të njëjtat burime, numëron çfarë *do* dërgonte secili konfigurim, pa dërguar
asgjë. B1 vazhdon normalisht; telefoni s'merr zhurmë shtesë.

**I kthyeshëm plotësisht:** `systemctl stop b0-counter && systemctl disable b0-counter` → gjithçka ndalon.

## Çfarë numëron

| Burimi | Tap | B0 (flat) | B1 (tri-shtresor) |
|---|---|---|---|
| **L2** InfluxDB threshold | Lokal (CT104) | mostra mbi prag (4 rregulla) | episode × 2 (Firing+Resolved) |
| **L1** Uptime Kuma | SSH → CT107, sqlite `heartbeat` | çdo ngjarje important | ≈ B0 (flap-guard i rrallë) |
| **L3** PVE+PBS tasks | SSH → pve1, PBS | çdo task i përfunduar | kategori OK distinkte/cikël + çdo dështim |

## Deploy (te CT104)

### Hapi 1 — çelësa SSH nga CT104 te burimet remote (një herë)

`b0_counter` lexon L1/L3 përmes SSH pa fjalëkalim. Nga CT104:

```bash
test -f /root/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519
for h in 192.168.20.24 192.168.20.10 192.168.20.30; do ssh-copy-id -i /root/.ssh/id_ed25519.pub root@$h; done
# testo (duhet të kthejë pa pyetur fjalëkalim):
for h in 192.168.20.24 192.168.20.10 192.168.20.30; do ssh -o BatchMode=yes root@$h hostname; done
```

> Nëse s'do L1/L3 tani (vetëm L2 lokal), lëri `UPTIME_KUMA_SSH`/`PVE_SSH`/`PBS_SSH` bosh te env — burimet kapërcehen pa gabim.

### Hapi 2 — vendos skriptin + config

```bash
mkdir -p /opt/b0-counter /etc/b0-counter /var/lib/b0-counter
# kopjo b0_counter.py te /opt/b0-counter/ (nga repo ose scp)
cp b0_counter.py /opt/b0-counter/
cp b0-counter.env.template /etc/b0-counter/env
chmod 600 /etc/b0-counter/env
nano /etc/b0-counter/env   # vendos INFLUX_TOKEN real (pa '#' para tij!)
```

### Hapi 3 — verifiko token-in te InfluxDB

```bash
grep '^INFLUX_TOKEN=' /etc/b0-counter/env | cut -d= -f2- | tr -d '\r\n '   # duhet 88 karaktere
```

### Hapi 4 — smoke test (një cikël me interval të shkurtër, PARA se ta besosh)

```bash
cd /opt/b0-counter
INFLUX_TOKEN=$(grep '^INFLUX_TOKEN=' /etc/b0-counter/env | cut -d= -f2- | tr -d '\r\n ') \
INFLUX_URL=http://localhost:8086 INFLUX_ORG=fie INFLUX_BUCKET=lab \
B0_INTERVAL_S=60 UPTIME_KUMA_SSH=root@192.168.20.24 PVE_SSH=root@192.168.20.10 PBS_SSH=root@192.168.20.30 \
timeout 75 python3 b0_counter.py
```

Prit ~1 minutë. Duhet të shohësh një rresht `cikli OK: B0=... B1=...`. Nëse ndonjë burim jep gabim SSH,
rregullo çelësin (Hapi 1) ose lëre bosh atë burim. **Mos vazhdo te Hapi 5 pa një cikël OK.**

### Hapi 5 — install si service

```bash
cp b0-counter.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now b0-counter
systemctl status b0-counter --no-pager
journalctl -u b0-counter -f    # shiko ciklet live
```

### Hapi 6 — panel Grafana ✅ (18 Korrik 2026, i verifikuar live)

Dashboard i importuar: **"Paper 4 — Live B0 vs B1"** (UID `paper4-b0-live`, folder AI-Lab), 6 panele:
B0 vs B1 kumulativ, stat "Reduktim aktual %", B0/B1 total, koha e ciklit të fundit, ndarje sipas L1/L2/L3.

Skedari: `grafana-b0-live-dashboard.json`. Për re-import: Grafana → Dashboards → New → Import → ngarko →
zgjidh datasource InfluxDB (`fie`/`lab`) → Import.

⚠️ Fix i aplikuar pas import-it: paneli "Cikli i fundit" fillimisht dilte "No data" sepse query-ja mbante
vetëm `_time` (jo `_value`) — Grafana s'e rendëron dot një stat panel pa `_value`. Fix: konverto `_time` në
epoch-ms (`int(v: r._time) / 1000000`) dhe vendose si `_value`. Query-ja e korrigjuar është tashmë te
skedari JSON. Verifikuar: paneli tregon "19 minutes ago" pas fix-it.

## Njoftim dështimi (shtuar 22 Korrik 2026)

B0 shadow counter është **vetëm-lexim, i heshtur me qëllim** — s'dërgon njoftime për numërimet vetë (kjo
do të ishte kundër qëllimit të dizajnit, shih më sipër). Por një alarm ka kuptim: nëse vetë
`b0-counter.service` dështon plotësisht (jo një burim i vetëm që degradohet, por vetë procesi), duam ta
dimë pa pritur 2-4 javë e pastaj ta zbulojmë se runi ka qenë bosh.

`OnFailure=b0-counter-notify.service` te `b0-counter.service` — systemd e thërret automatikisht kur cikli
dështon (jo çdo herë që `Restart=always` e rinis normalisht për një gabim kalimtar, por kur systemd e sheh
si "failed"). `b0-counter-notify.service` xhiron `b0_notify_failure.sh` (curl → ntfy `/critical`).

**Deploy shtesë** (pas Hapit 5 më sipër):

```bash
cp b0-counter-notify.service /etc/systemd/system/
cp b0_notify_failure.sh /opt/b0-counter/
chmod +x /opt/b0-counter/b0_notify_failure.sh
nano /etc/b0-counter/env   # shto NTFY_PASS real (NTFY_USER=genci, NTFY_URL tashmë të vendosur)
systemctl daemon-reload
# smoke test — duhet të vijë njoftim critical brenda pak sekondash:
systemctl start b0-counter-notify.service
journalctl -u b0-counter-notify -n 5 --no-pager
```

## Sa gjatë?

Lëre 2-4 javë. Sa më gjatë, aq më i fortë krahasimi live. Rezultati final: `b0_total / b1_total` mbi periudhën
→ % reduktim live, për ta krahasuar me 83.9% të simulimit historik.

## Ndalimi (kthim i plotë)

```bash
systemctl disable --now b0-counter
rm -f /etc/systemd/system/b0-counter.service /etc/b0-counter/env
rm -rf /opt/b0-counter /var/lib/b0-counter /etc/b0-counter
systemctl daemon-reload
```

Të dhënat te InfluxDB (`b0_shadow`) mbeten për analizë; fshihen vetë me retention-in e bucket-it, ose
manualisht me `influx delete`.

## Kufizime (për t'u cituar te paper-i)

- L1 flap-guard dhe L3 dedup modelohen **për-cikël** (jo me gjendje të vazhdueshme ndër-cikle si simulimi
  historik). Në cikël orësh kjo është përafrim i mirë (dedup info = 1h), por jo identik — cito si "live
  approximation", numri autoritar mbetet simulimi historik.
- B1_L2 supozon 2 njoftime/episod (Firing+Resolved), njësoj si simulimi.
- Nëse një burim SSH bie përkohësisht, ai cikël e nën-numëron atë burim (degradim i qetë) — boshllëqet
  duken te `journalctl`.
