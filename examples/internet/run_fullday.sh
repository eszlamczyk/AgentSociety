#!/usr/bin/env bash
# Runs the internet-example full-day simulation with all logs, run.log, and
# generated plots grouped under one date-prefixed directory:
#
#   logs/<label>/plan_logs/plan_logs.jsonl
#   logs/<label>/internet_logs/{device_usage,antenna_device_connections,all_internet_activity}_logs.jsonl
#   logs/<label>/position_logs/position_logs.jsonl
#   logs/<label>/metrics_output/{steps,agents,guardrails}.csv
#   logs/<label>/run.log
#   logs/<label>/plots/*.png
#
# Usage:
#   ./run_fullday.sh                # label = today's date (YYYY-MM-DD)
#   ./run_fullday.sh 2026-09-20_final   # custom label
#
# Set CLEAR_LOGS_ON_START=0 to append to an existing label's logs instead of
# truncating them (the default truncates, matching a fresh full-day run).
#
# If the simulation crashes or is interrupted part-way, the plots are STILL
# generated from whatever got logged (a partial day is still data — the
# 2026-08-23 100-agent run died at step 175/288 and was worth keeping), and
# the script exits with the simulation's own exit status so a wrapper can
# tell the two cases apart.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

LABEL="${1:-$(date +%Y-%m-%d)}"
LOG_ROOT="logs/${LABEL}"
mkdir -p "$LOG_ROOT"

export PLAN_LOG_DIR="${LOG_ROOT}/plan_logs"
export INTERNET_LOG_DIR="${LOG_ROOT}/internet_logs"
export POSITION_LOG_DIR="${LOG_ROOT}/position_logs"
export METRICS_OUT_DIR="${LOG_ROOT}/metrics_output"
export CLEAR_LOGS_ON_START="${CLEAR_LOGS_ON_START:-1}"

PYTHON="python3"
if [ -x "../../.venv/bin/python3" ]; then
    PYTHON="../../.venv/bin/python3"
fi

echo "=== Running full-day simulation -> ${LOG_ROOT} ==="
# Don't let `set -e`/pipefail abort the script on a simulation crash: we want
# the plots below regardless. PIPESTATUS[0] is python's status, not tee's.
set +e
"$PYTHON" internet.py 2>&1 | tee "${LOG_ROOT}/run.log"
SIM_STATUS=${PIPESTATUS[0]}
set -e

if [ "$SIM_STATUS" -ne 0 ]; then
    echo "=== Simulation exited with status ${SIM_STATUS} — generating plots from the partial logs anyway ==="
fi

# metrics/{mobility,activity,traffic}_analysis.py expect run_dir/positions and
# run_dir/internet subdirs (an older naming convention); the loggers above
# write position_logs/ and internet_logs/. Symlink rather than touch either
# side, so this stays a pure plumbing fix.
ln -sfn position_logs "${LOG_ROOT}/positions"
ln -sfn internet_logs "${LOG_ROOT}/internet"

echo "=== Generating plots -> ${LOG_ROOT}/plots ==="
PLOT_FAILURES=0
for script in mobility_analysis activity_analysis traffic_analysis guardrail_analysis; do
    if ! "$PYTHON" "metrics/${script}.py" "$LOG_ROOT"; then
        echo "=== metrics/${script}.py failed (see above) — continuing with the remaining plots ==="
        PLOT_FAILURES=$((PLOT_FAILURES + 1))
    fi
done

if [ "$SIM_STATUS" -ne 0 ]; then
    echo "=== Done (simulation FAILED with status ${SIM_STATUS}, ${PLOT_FAILURES} plot script(s) failed). Partial results under ${LOG_ROOT}/ ==="
else
    echo "=== Done (${PLOT_FAILURES} plot script(s) failed). Everything for this run lives under ${LOG_ROOT}/ ==="
fi
exit "$SIM_STATUS"
