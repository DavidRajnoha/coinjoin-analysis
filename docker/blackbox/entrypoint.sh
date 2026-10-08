#!/usr/bin/env bash
# Blackbox CoinJoin Sudoku + chain attribution over a time window of a coinjoin_tx_info.json.
# Resumable: every step skips work whose output already exists under $WORK, so rerunning the
# same command after an interruption continues where it stopped.
set -euo pipefail

INPUT=${INPUT:-/data/coinjoin_tx_info.json}
WORK=/work   # fixed: the solver cache link /app/subset_cache points here
FROM=${FROM:-2025-01-01}
TO=${TO:-2025-11-29}
AUGMENT=${AUGMENT:-1}
CHUNKS=${CHUNKS:-40}
WORKERS=${WORKERS:-auto}
GB_PER_WORKER=${GB_PER_WORKER:-4}
NAME=${NAME:-window_${FROM}_${TO}$([ "$AUGMENT" = 1 ] && echo _augmented || true)}
EXTRA_ARGS=${EXTRA_ARGS:-}
PROGRESS_EVERY=${PROGRESS_EVERY:-300}
RUN="$WORK/$NAME"

log() { echo "[$(date '+%F %T')] $*"; }

cd /app
mkdir -p "$WORK/subset_cache"
# Everything printed below also goes to /work/<NAME>.log
exec > >(tee -a "$WORK/$NAME.log") 2>&1

if [ "$WORKERS" = auto ]; then
  avail_kb=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
  limit=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max)
  [ "$limit" != max ] && [ "$((limit / 1024))" -lt "$avail_kb" ] && avail_kb=$((limit / 1024))
  by_mem=$(( (avail_kb / 1024 / 1024 - 2) / GB_PER_WORKER ))
  WORKERS=$(( by_mem < $(nproc) ? by_mem : $(nproc) ))
  [ "$WORKERS" -lt 1 ] && WORKERS=1
fi
log "run=$RUN window=$FROM..$TO augment=$AUGMENT chunks=$CHUNKS workers=$WORKERS"

# 1. Window + block files
if [ ! -d "$RUN/btc-node" ]; then
  [ -f "$INPUT" ] || { echo "input not found: $INPUT (mount it, e.g. -v /path/to/dir:/data)"; exit 1; }
  log "preparing window from $INPUT"
  flag=$([ "$AUGMENT" = 1 ] && echo --augment || echo --no-augment)
  python docker/blackbox/prepare_window.py --input "$INPUT" --run "$RUN" --from "$FROM" --to "$TO" $flag
else
  log "window already prepared, reusing it: $(cat "$RUN/window_summary.json" 2>/dev/null | tr -d '\n ')"
fi

# 2. Solver matrices, once, before parallel workers
python docker/blackbox/pregen_subsets.py

# 3. Chunks
if [ ! -d "$RUN/_chunks" ]; then
  python scripts/parallel_blackbox.py split "$RUN" "$CHUNKS"
fi
mapfile -t todo < <(for c in "$RUN"/_chunks/chunk_*; do
  [ -f "$c/analysis_cache/blackbox_cj_objs.pkl" ] || echo "$c"; done)
total=$(ls -d "$RUN"/_chunks/chunk_* | wc -l)
log "$(( total - ${#todo[@]} ))/$total chunks already solved, ${#todo[@]} to go"

# 4. Solve, with a progress line every $PROGRESS_EVERY seconds
progress() {
  set +e +o pipefail   # a counting glitch must never stop the reporter
  local total_tx start=$(date +%s)
  total_tx=$(python -c "import json; print(json.load(open('$RUN/window_summary.json'))['coinjoins'])" 2>/dev/null || echo '?')
  local done0
  done0=$(cat "$RUN"/_chunks/chunk_*/run.log 2>/dev/null | grep -c 'solve_sudoku_for_coinjoin_set: \(solving\|skipping\)' || true)
  while sleep "$PROGRESS_EVERY"; do
    local done_tx chunks mem el rate eta
    done_tx=$(cat "$RUN"/_chunks/chunk_*/run.log 2>/dev/null | grep -c 'solve_sudoku_for_coinjoin_set: \(solving\|skipping\)' || true)
    chunks=$(find "$RUN"/_chunks -name blackbox_cj_objs.pkl 2>/dev/null | wc -l)
    mem=$(awk '/MemAvailable/ {printf "%.1f", $2/1048576}' /proc/meminfo)
    el=$(( $(date +%s) - start ))
    eta='?'
    if [ "$total_tx" != '?' ] && [ "$done_tx" -gt "$done0" ]; then
      eta=$(( el * (total_tx - done_tx) / (done_tx - done0) / 60 ))min
    fi
    log "progress: $done_tx/$total_tx transactions started, $chunks/$total chunks solved, elapsed $((el / 60))min, remaining ~$eta (rough), free memory ${mem}GB"
  done
}
if [ "${#todo[@]}" -gt 0 ]; then
  log "solving: per-chunk solver output in $RUN/_chunks/chunk_XX/run.log"
  progress &
  progress_pid=$!
  printf '%s\n' "${todo[@]}" | xargs -P "$WORKERS" -I{} sh -c '
    python joinmarket/unified_analysis.py "{}" --analysis blackbox --collect-stats > "{}/run.log" 2>&1 \
      && echo "[$(date "+%F %T")] solved $(basename {})" \
      || echo "[$(date "+%F %T")] FAILED $(basename {}) - see {}/run.log"'
  kill "$progress_pid" 2>/dev/null || true
fi
missing=$(for c in "$RUN"/_chunks/chunk_*; do [ -f "$c/analysis_cache/blackbox_cj_objs.pkl" ] || echo x; done | wc -l)
if [ "$missing" -gt 0 ]; then
  log "$missing chunks unsolved - rerun the same command to resume"; exit 1
fi

# 5. Merge, chain and report over the whole window
python scripts/parallel_blackbox.py merge "$RUN"
log "building chains and report (output in $RUN/final_run.log)"
python joinmarket/unified_analysis.py "$RUN" --analysis blackbox $EXTRA_ARGS > "$RUN/final_run.log" 2>&1
python docker/blackbox/summarize.py "$RUN"
log "done: $RUN/report_unified/ and $RUN/thesis_tables.json"
