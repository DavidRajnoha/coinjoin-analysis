# Blackbox attack container

Runs the real-world blackbox analysis of the master thesis (§3.4.5): the CoinJoin Sudoku on
every transaction of a time window, then role chaining over the whole window. Input is a
`coinjoin_tx_info.json` on the machine where it runs.

## Build and publish

```
docker build -f docker/blackbox/Dockerfile -t jm-blackbox .
docker tag jm-blackbox ghcr.io/<user>/jm-blackbox:latest
docker push ghcr.io/<user>/jm-blackbox:latest
```
Without a registry: `docker save jm-blackbox | gzip > jm-blackbox.tar.gz`, copy the file, then
`docker load < jm-blackbox.tar.gz` on the other machine.

## Run

```
docker run --rm --user $(id -u):$(id -g) \
  -v /path/to/dir/with/json:/data:ro \
  -v /path/to/work:/work \
  ghcr.io/<user>/jm-blackbox:latest
```

| variable | default | meaning |
|---|---|---|
| `INPUT` | `/data/coinjoin_tx_info.json` | input file inside the container |
| `FROM`, `TO` | `2025-01-01`, `2025-11-29` | window, inclusive, by broadcast date (the thesis window) |
| `AUGMENT` | `1` | recover JoinMarket coinjoins hidden as post-mix by Wasabi 1 precedence. Needs the `postmix` section and loads the whole file: about 6-8x its size in RAM. `0` streams only `coinjoins` |
| `CHUNKS` | `40` | number of parallel work units |
| `WORKERS` | `auto` | parallel solvers; auto = available RAM / `GB_PER_WORKER`, capped at CPU count |
| `GB_PER_WORKER` | `4` | memory budget per solver |
| `NAME` | from window | run folder name under `/work` |
| `EXTRA_ARGS` | | extra flags for the final chaining run, e.g. `--maker-sessions` |
| `PROGRESS_EVERY` | `300` | seconds between progress lines while solving |

Pass variables with `-e NAME=value`.

## Watching a run

The console shows each step and, while solving, a progress line every `PROGRESS_EVERY` seconds
(default 300):
```
[2026-10-08 07:52:31] progress: 6/37 transactions started, 0/2 chunks solved, elapsed 0min, remaining ~3min (rough), free memory 17.1GB
[2026-10-08 08:00:39] solved chunk_01
```
The remaining-time estimate is rough: large transactions take far longer than small ones.

- Detached: start with `docker run -d --name jmbb ...`, then `docker logs -f jmbb`.
- The same console output is appended to `/work/<NAME>.log`.
- Solver detail per chunk: `/work/<NAME>/_chunks/chunk_XX/run.log`
  (e.g. `tail -f` to watch the transaction being solved).
- Final chaining and report run: `/work/<NAME>/final_run.log`.

## Resuming

Every step skips work already present under `/work`. After an interruption, run the same
command again: solved chunks are kept and only the rest are solved. To change `CHUNKS`, delete
`/work/<NAME>/_chunks` first.

## Output

`/work/<NAME>/`:
- `report_unified/unified_coinjoin_report.html`, `.json`: the full report with chains.
- `thesis_tables.json`: solved / skipped / unsolved (Table 3.9), solution counts (Table 3.10),
  chain and taker-output totals.
- `analysis_cache/`: merged solver results, so the report can be rebuilt in another mode
  without solving again.
- `window_summary.json`, `coinjoin_tx_info.json`, `btc-node/`: the window that was analysed.

`/work/subset_cache/` holds the solver's precomputed matrices (1.6 GB), generated once.
