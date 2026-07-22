#!/bin/sh
# b0_notify_failure.sh — njofton ntfy kur b0-counter.service dështon.
# Xhirohet nga b0-counter-notify.service (OnFailure= te b0-counter.service).
# Kërkon NTFY_USER/NTFY_PASS te /etc/b0-counter/env (shih b0-counter.env.template).

set -eu

: "${NTFY_USER:?mungon NTFY_USER te env}"
: "${NTFY_PASS:?mungon NTFY_PASS te env}"
NTFY_URL="${NTFY_URL:-http://192.168.20.25/critical}"

curl -s -m 10 -u "${NTFY_USER}:${NTFY_PASS}" \
    -H "Priority: urgent" \
    -H "Title: B0 counter (Paper 4) deshtoi" \
    -H "Tags: warning" \
    -d "b0-counter.service ka deshtuar ne $(hostname) — kontrollo: journalctl -u b0-counter -n 50" \
    "${NTFY_URL}" >/dev/null
