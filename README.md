# multitier-lab-alerting

Reference implementation, raw evaluation data, and reproduction scripts for the paper
**"Context-Aware Multi-Tier Alerting for Heterogeneous On-Premise Laboratory Telemetry"**
(UPT, Faculty of Electrical Engineering — Measurement Lab).

The paper proposes a three-layer alerting model — availability (L1), metrics/threshold (L2), and
native system events (L3) — with an explicit decision rule (`signal → layer → severity → channel`,
deduplication + flap-guard suppression) validated against a flat, single-tier baseline (B0) using 20
days of real signals replayed identically through both configurations. The multi-tier model (B1)
reduces notification volume by **83.9%** (1406 → 227) with zero false negatives on critical signals.

## What's in this repository

| Path | Contents |
|---|---|
| `scripts/simulate_b0_b1.py` | Core B0 (flat) vs B1 (multi-tier) replay simulator — the primary evaluation script (§5.1 of the paper). Reads the raw signal CSVs in `data-raw/` and reproduces the headline 1406 → 227 result. |
| `scripts/latency_sensor_dashboard.py` | Sensor-to-dashboard latency measurement (MQTT publish → InfluxDB queryable), §5.3. |
| `scripts/latency_ntfy_dispatch.py` | Event-to-notification-dispatch latency (trigger → ntfy server ack), §5.3. |
| `scripts/loadtest_mqtt.py` | MQTT ingestion throughput / loss-point load test, §5.4. |
| `scripts/b0_counter.py` + `b0-counter.service` + `b0-counter.env.template` | The live, read-only "shadow counter" used for forward-looking validation (§5.2) — taps the same three signal sources in production and counts what each configuration *would* have sent, without touching live alerting. |
| `scripts/b0_notify_failure.sh` + `b0-counter-notify.service` | Optional systemd `OnFailure=` hook — sends a push notification if the shadow counter itself stops running, so a multi-week unattended run doesn't silently go dark. |
| `data-raw/` | Raw extracted signals for the 20-day evaluation window (27 June – 17 July 2026): `l1_uptimekuma_important.csv`, `l3_pve_tasks.csv`, `l3_pbs_tasks.csv`, `l2_influx_thresholds_summary.csv`, plus the latency and load-test raw samples. |
| `grafana-b0-live-dashboard.json` | Importable Grafana dashboard for the live B0-vs-B1 shadow run. |
| `B0-LIVE-RUN.md` | Full deployment runbook for the live shadow counter, including the design rationale for using a read-only tap instead of reconfiguring production alerting. |

## Reproducing the primary result (§5.1)

```bash
python3 scripts/simulate_b0_b1.py \
    --l1 data-raw/l1_uptimekuma_important.csv \
    --l3-pve data-raw/l3_pve_tasks.csv \
    --l3-pbs data-raw/l3_pbs_tasks.csv \
    --l2 data-raw/l2_influx_thresholds_summary.csv
```

Expected output: B0 = 1406, B1 = 227, reduction = 83.9%. No external services are required for this
script — it operates entirely on the CSV snapshots in `data-raw/`.

## Reproducing latency / throughput measurements (§5.3–5.4)

The latency and load-test scripts require a live deployment (MQTT broker, InfluxDB v2, ntfy) and are
provided primarily for methodological transparency — the exact instrumentation used to produce the
numbers reported in the paper — rather than for out-of-the-box reruns against someone else's
infrastructure. Each script documents its required environment variables and connection parameters at
the top of the file. No credentials are stored in this repository; all scripts read secrets from
environment variables at runtime.

## The live shadow counter (§5.2)

`b0_counter.py` is deployed as a systemd service that queries the same three signal sources used in
`simulate_b0_b1.py`, but against live, ongoing data, and writes both counts (B0, B1) to InfluxDB every
hour. It never sends a real notification — it only counts what each configuration *would* send — so it
runs alongside production alerting without any risk of duplicate or missing alerts. See
`B0-LIVE-RUN.md` for the full rationale and deployment steps.

## Methodological notes and limitations

- Suppression parameters (60 s critical dedup, 3600 s info dedup, 60 s flap-guard) are explicit
  measurement-methodology choices, not values extracted from a pre-existing production policy — they
  should be cited as evaluation parameters.
- L2 (metrics/threshold) is reconstructed from InfluxDB aggregate queries (samples-over-threshold,
  episode count) rather than a per-event log, since Grafana's alert evaluation produces continuous
  state rather than discrete log entries. B1(L2) is modeled as two notifications per episode
  (Firing + Resolved), matching Grafana's actual behavior.
- The live shadow counter approximates deduplication *per hourly cycle* rather than with continuous
  cross-cycle state, which is a coarser approximation than the historical replay simulator. The
  historical replay result (83.9%) remains the authoritative figure; the live run is a forward-looking
  corroboration.

## License

MIT — see `LICENSE`.

## Citation

See `CITATION.cff`. If you use this code or dataset, please cite both the accompanying paper and this
repository.
