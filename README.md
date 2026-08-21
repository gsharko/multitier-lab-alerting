# multitier-lab-alerting

Reference implementation, raw evaluation data, and reproduction scripts for the paper
**"Duration-Dependent Suppression in Multi-Tier Fault Management: A Paired Replay and Live-Shadow
Evaluation of Notification Policies"** by Anni Dasho (Luarasi University, Tirana) and Genci Sharko
(Faculty of Electrical Engineering, Polytechnic University of Tirana).

The paper proposes a three-layer alerting model — availability (L1), metrics/threshold (L2), and
native system events (L3) — with an explicit decision rule (`signal → layer → severity → channel`,
deduplication + flap-guard suppression) validated against a flat, single-tier baseline (B0), first
by replaying 20 days of real signals identically through both configurations (§5.1), then by running
both configurations live in parallel as a shadow counter for 29 days (§5.2). On the event-based
layers (L1+L3, discrete per-signal counting) the multi-tier model (B1) reduces notification volume by
**63.9% in replay and 54.1% live**, with zero false negatives on critical signals in either window.
The aggregate figures — 83.9% replay / 25.0% live — include the metrics/threshold layer (L2), whose
episode-based counting is dominated by a single long-lived disk-full condition in the replay window;
see §5.2/§7.1 of the paper and `B0-LIVE-RUN.md` for the full breakdown. **83.9% alone is not the
paper's result** and should not be cited without this context.

## What's in this repository

| Path | Contents |
|---|---|
| `scripts/simulate_b0_b1.py` | Core B0 (flat) vs B1 (multi-tier) replay simulator — the primary evaluation script (§5.1 of the paper). Reads the raw signal CSVs in `data-raw/` and reproduces the replay-window result (1406 → 227 aggregate; 507 → 183 on the event-based layers). |
| `scripts/make_figures.py` | Generates the paper's result figures from `data-raw/` — the replay decomposition (Fig. 3), the per-object composition of the live availability-layer signals (Fig. 4), and the live cumulative B0-vs-B1 chart (Fig. 5). |
| `scripts/latency_sensor_dashboard.py` | Sensor-to-dashboard latency measurement (MQTT publish → InfluxDB queryable), §5.3. |
| `scripts/latency_ntfy_dispatch.py` | Event-to-notification-dispatch latency (trigger → ntfy server ack), §5.3. |
| `scripts/loadtest_mqtt.py` | MQTT ingestion throughput / loss-point load test, §5.4. |
| `scripts/b0_counter.py` + `b0-counter.service` + `b0-counter.env.template` | The live, read-only "shadow counter" used for forward-looking validation (§5.2) — taps the same three signal sources in production and counts what each configuration *would* have sent, without touching live alerting. |
| `scripts/b0_notify_failure.sh` + `b0-counter-notify.service` | Optional systemd `OnFailure=` hook — sends a push notification if the shadow counter itself stops running, so a multi-week unattended run doesn't silently go dark. |
| `data-raw/` | Raw extracted signals for the 20-day replay window (27 June – 17 July 2026): `l1_uptimekuma_important.csv`, `l3_pve_tasks.csv`, `l3_pbs_tasks.csv`, `l2_influx_thresholds_summary.csv`, plus the latency and load-test raw samples. `b0_shadow_live_daily.csv` holds the 29-day live shadow run's daily B0/B1 series (18 July – 16 August 2026), and `l1_uptimekuma_live_important.csv` (140 rows, reconciling exactly with the reported B0(L1) = 140) with its per-object summary `l1_uptimekuma_live_bymonitor.csv` carry the availability-layer composition behind §5.2. The free-text `msg` column has its internal addresses replaced by `<host>:<port>`; no script reads that column and no reported number derives from it. |
| `grafana-b0-live-dashboard.json` | Importable Grafana dashboard for the live B0-vs-B1 shadow run. |
| `figures/` | Paper figures: the multi-tier decision model (§3), the alerting integration architecture (§4), the replay decomposition by layer (Fig. 3, §5.1), the per-object composition of the live availability-layer signals (Fig. 4, §5.2), and the live cumulative B0-vs-B1 chart (Fig. 5, §5.2). |
| `B0-LIVE-RUN.md` | Full deployment runbook for the live shadow counter, including the design rationale for using a read-only tap instead of reconfiguring production alerting. |

## Reproducing the replay result (§5.1)

```bash
python3 scripts/simulate_b0_b1.py \
    --l1 data-raw/l1_uptimekuma_important.csv \
    --l3-pve data-raw/l3_pve_tasks.csv \
    --l3-pbs data-raw/l3_pbs_tasks.csv \
    --l2 data-raw/l2_influx_thresholds_summary.csv
```

Expected output: B0 = 1406, B1 = 227, aggregate reduction = 83.9%; event-based layers (L1+L3)
507 → 183, reduction = 63.9%. No external services are required for this script — it operates
entirely on the CSV snapshots in `data-raw/`.

**Read the aggregate figure with care.** It is dominated by a single long-lived `truenas-backups`
disk-full condition (830 samples across 3 episodes, 59% of all B0 signals in the replay window) —
without it the aggregate reduction collapses, as the 29-day live shadow run confirmed (25.0%
aggregate, against 83.9% in replay). The event-based figure (63.9% replay / 54.1% live) is stable
across both windows and is the paper's primary claim; see §5.2/§7.1 and `B0-LIVE-RUN.md`.

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
runs alongside production alerting without any risk of duplicate or missing alerts.

The run reported in the paper closed after 29 days (18 July – 16 August 2026): B0 = 1555, B1 = 1166,
aggregate reduction 25.0%; event-based layers (L1+L3) 1007 → 462, reduction 54.1%, zero false
negatives. See `B0-LIVE-RUN.md` for the full rationale, deployment steps, and the layer-by-layer
breakdown of why the aggregate figure diverges from replay.

## Methodological notes and limitations

- Suppression parameters (60 s critical dedup, 3600 s info dedup, 60 s flap-guard) are explicit
  measurement-methodology choices, not values extracted from a pre-existing production policy — they
  should be cited as evaluation parameters.
- L2 (metrics/threshold) is reconstructed from InfluxDB aggregate queries (samples-over-threshold,
  episode count) rather than a per-event log, since Grafana's alert evaluation produces continuous
  state rather than discrete log entries. B1(L2) is modeled as two notifications per episode
  (Firing + Resolved), matching Grafana's actual behavior.
- The live shadow counter approximates deduplication *per hourly cycle* rather than with continuous
  cross-cycle state, which is a coarser approximation than the historical replay simulator.
- The two windows disagree on the aggregate figure (83.9% replay vs 25.0% live) because L2's
  episode-based counting is sensitive to episode length: it compresses when episodes run long
  (replay, dominated by one multi-hour disk-full condition) and can *inflate* notification volume
  when episodes are short (live, 1.56 samples/episode on average). The event-based layers (L1+L3) do
  not have this failure mode and agree closely across windows (63.9% replay / 54.1% live) — this is
  the figure the paper treats as validated. See §5.2/§7.1 of the paper for the full analysis.

## License

MIT — see `LICENSE`.

## Citation

See `CITATION.cff`. If you use this code or dataset, please cite both the accompanying paper and this
repository.
