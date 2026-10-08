# FINDINGS.md rerun on the 2026 corpus

Corpus: `data/joinmarket/real-data-2026/coinjoin_tx_info.json` (2.5 GB), compared with the
`real-data` corpus that `../FINDINGS.md` was written from. Same scripts, same definitions.
Everything in this folder is regenerable; see "Reproducing" below.

## Headline comparison

| metric | FINDINGS (2025 corpus) | 2026 corpus |
|---|---|---|
| labeled coinjoins | 24,135 | **156,352** (6.5×) |
| span | 2015-01-02 → 2025-11-28 | 2015-01-02 → 2026-10-05 |
| outputs | 279,165 | 1,835,657 |
| with a recorded spender | 98.9% | 98.6% |
| mixed share / median mixed per tx | 51.9% / 6 | 51.6% / 6 |
| **remix rate, lower bound** (known) | 32.9% | **73.4%** |
| remix rate, upper bound (N≥3) | 61.3% | 93.5% |
| respent outside the observable set | 37.6% | 5.1% |
| never spent | 1.1% | 1.4% |
| candidates (N≥3) | 15,926 (66% of corpus) | 30,328 (19% of corpus) |
| remix by age 30 / 90 / 180 / 365 d | 31.5 / 32.9 / 33.5 / 34.3% | 68.6 / 72.3 / 73.6 / 75.2% |
| converged? | yes, by ~90 d | **no**, 3.0 pp spread over the last 3 ages |

## §2.3 Threshold sensitivity

| N | ext txs | outputs | upper bound |
|---|---|---|---|
| 2 | 37,811 | 386,143 | 94.5% |
| **3** | **30,328** | **369,448** | **93.5%** |
| 4 | 26,150 | 355,226 | 92.8% |
| 5 | 22,629 | 338,968 | 91.9% |
| 8 | 14,133 | 281,148 | 88.7% |
| 12 | 7,643 | 213,887 | 85.1% |
| 20 | 3,293 | 144,629 | 81.3% |

The bound is much less threshold-sensitive than before (old: 75.0% → 34.2% across N).

## §3 Value dependence (90-day window, mixed outputs)

| amount | txs | remix rate (old) | **remix rate (2026)** | not in corpus (old → 2026) |
|---|---|---|---|---|
| <0.01 | 22,010 | 3.5% | **54.6%** | 94.3% → 37.2% |
| 0.01–0.1 | 42,494 | 9.9% | 61.7% | 86.7% → 34.7% |
| 0.1–0.5 | 35,413 | 15.5% | 67.4% | 82.4% → 30.7% |
| 0.5–1 | 15,555 | 32.2% | 75.4% | 66.4% → 23.2% |
| 1–5 | 24,975 | 42.7% | 80.0% | 56.2% → 18.7% |
| 5–20 | 11,830 | 53.7% | **80.9%** | 45.3% → 18.0% |
| >20 | 2,503 | 54.5% | 70.8% | 44.0% → 27.7% |

The ~15× spread is now ~1.5×, and the trend is no longer monotone (it drops above 20 BTC).
Most of the old value effect was a **detection artifact**: the old corpus under-labeled small
coinjoins. The amount mix changed with it. Sub-1 BTC transactions were 6–20% of 2017–19 in
the old corpus and are 54–65% now. The 0.1–0.5 bucket held 1–4% of 2017–19 before and holds
20–25% now.

Per-year 90-day remix rates: 80–90% in 2015–2020, 64.2% in 2021, **45.1% / 47.6% in
2022 / 23**, 64.6% in 2024, 52.0% in 2025, 47.7% in 2026. **The 2022–23 dip survives the
relabeling.** In those years the candidate share (41–45% of outputs) is also the highest,
so the dip may still be a labeling gap and not a change in behaviour.

## §4 Connectivity (JM = corpus + output- and input-side candidates)

| metric | all (old → new) | **≥1 BTC (old → new)** | ≥5 BTC | ≥10 BTC |
|---|---|---|---|---|
| n | 24,135 → 156,352 | 15,935 → **39,351** | 14,339 | 7,196 |
| output: all traced | 26.6 → 60.3% | 35.7 → **60.5%** | 59.0% | 54.9% |
| output: all but one | 32.0 → 32.8% | 39.3 → 35.5% | 36.3% | 39.1% |
| **output: a + abo** | 58.5 → 93.0% | 75.0 → **96.1%** | 95.3% | 94.1% |
| input: all traced | 15.2 → 65.7% | 20.5 → 63.7% | 64.5% | 61.7% |
| input: all but one | 13.8 → 21.1% | 17.8 → 20.8% | 19.5% | 21.4% |
| both sides fully traced | 6.7 → 43.2% | 9.2 → 41.0% | 38.0% | 33.2% |
| **both sides all-but-one** | 5.7 → 8.6% | 7.4 → **8.3%** | 6.7% | 7.5% |
| outputs 5+ unexplained | 11.1 → 1.3% | 1.5 → 0.4% | 0.6% | 1.2% |
| inputs 5+ unexplained | 42.4 → 3.0% | 29.9 → 3.6% | 4.2% | 4.0% |

- The both-sides all-but-one frequency barely moved (7.4% → 8.3% at ≥1 BTC). In absolute
  numbers it went from 1,367 to **3,277** txids (`both_sides_all_but_one.txt`).
- **H4 (higher value ⇒ easier) no longer holds as stated.** The metrics are flat or fall
  with amount above 1 BTC.
- The input side is no longer the binding constraint: 3.6% have 5+ unexplained inputs, down from 29.9%.

### §4.1 Per-year, ≥1 BTC

| year | txs | out all | out abo | out a+abo | in all | in abo | both all | both abo |
|---|---|---|---|---|---|---|---|---|
| 2015 | 2,419 | 61.7% | 34.6% | 96.2% | 63.3% | 22.8% | 42.9% | 9.5% |
| 2016 | 10,267 | 61.7% | 36.8% | 98.5% | 63.5% | 19.9% | 42.0% | 8.0% |
| 2017 | 5,613 | 60.1% | 36.4% | 96.5% | 58.6% | 20.1% | 37.3% | 8.2% |
| 2018 | 4,649 | 70.0% | 28.3% | 98.3% | 73.0% | 15.7% | 51.8% | 4.4% |
| 2019 | 6,847 | 72.3% | 26.4% | 98.7% | 75.9% | 16.1% | 54.0% | 3.6% |
| 2020 | 3,115 | 54.9% | 39.4% | 94.3% | 61.4% | 23.5% | 34.9% | 11.6% |
| 2021 | 1,812 | 53.6% | 37.8% | 91.4% | 61.5% | 21.7% | 34.8% | 11.0% |
| 2022 | 568 | 41.7% | 50.0% | 91.7% | 54.0% | 16.7% | 26.1% | 6.0% |
| 2023 | 665 | 26.9% | 59.2% | 86.2% | 35.9% | 36.4% | 15.3% | **26.6%** |
| 2024 | 2,814 | 40.6% | 49.2% | 89.8% | 47.2% | 34.3% | 19.3% | 16.2% |
| 2025 | 368 | 35.3% | 42.9% | 78.3% | 35.6% | 34.2% | 17.4% | 15.8% |
| 2026 † | 214 | 19.2% | 36.9% | 56.1% | 40.7% | 37.9% | 8.9% | 13.6% |

† Right-censored. The old claim that "`both abo` holds at 6.3–7.6% across 2015–2021" **no
longer holds**: it now ranges from 3.6% to 11.6%. From 2022 on, `both abo` rises sharply as
`both all` falls.

## §5 Traffic density (≥1 BTC, months with n≥30)

117 months (median 235 tx/month, range 30–1,561), up from 83.

| metric | raw r (old → new) | within-year r (old → new) |
|---|---|---|
| output: all traced | +0.42 → +0.57 | +0.59 → **+0.40** |
| output: all + all-but-one | +0.50 → +0.48 | +0.65 → **+0.27** |
| both sides all-but-one | +0.31 → **−0.34** | +0.39 → **−0.18** |

**H5 is substantially weakened.** The within-year effect fell by more than half. For the
both-sides signal it reversed sign. FINDINGS flagged this as the result most exposed to
labeling quality, and that is what happened.

## §8.1 Emulation calibration: lag until all mixed outputs are remixed

| unit | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|
| days (old) | 2.5 | 9.2 | 29.7 | 59.0 | 160.7 |
| **days (2026)** | **6.6** | 23.5 | **71.5** | 135.2 | 354.5 |
| intervening JM txs (old) | 36 | 104 | 288 | 511 | 1,911 |
| **intervening JM txs (2026)** | **443** | 1,366 | **3,675** | 6,819 | 18,080 |

Within 50 / 100 / 500 txs: 9.6% / 18.3% / 52.9% (old: 58.4 / 74.3 / 94.9%). The sample is
n = 93,591.

The tx-count unit is inflated because the corpus is ~6.5× denser per unit time. That is why
FINDINGS preferred it as the transfer unit, so the **§8 cool-down target of ~290
intervening JM txs is now ~3,700**. Lags in days also roughly doubled. H1 timescale:
fully-mixed 443 vs all-but-one 393 intervening txs (old: 38 vs 35). The two are still
comparable, so that argument for H1 holds.

## §6 / invariants

- `verify_disjoint.py`: all 4 checks pass on the new candidate set.
- **Not rerun:** the structural API check (`verify_candidates_via_api.py`), which queries
  mempool.space live. The random-chain baseline does not depend on the corpus, so there is
  nothing to rerun.

## Hypotheses, revisited

| # | old verdict | on 2026 data |
|---|---|---|
| H1 | plausible, unproven | unchanged. The pattern is common (35.5% out-abo at ≥1 BTC) and resolves on the same timescale as fully-mixed |
| H2 | plausible, unproven | unchanged in frequency (8.3%), but no longer stable per year |
| H4 | supported | **not supported as stated.** Remix rises with value up to ~1 BTC, then flattens; connectivity is flat |
| H5 | supported | **weak / not supported.** Within-year r = +0.27; the both-sides metric is negative |
| H6 | supported | still supported, but the gap shrank from 66% to 19% of corpus size. The 2021+ candidate share stays high (25–45% of outputs) |

## Reproducing

```
C=data/joinmarket/real-data-2026/coinjoin_tx_info.json; D=analysis_output/2026
.venv/bin/python analysis_output/mainnet_remix_analysis.py --corpus $C --out $D
.venv/bin/python analysis_output/jm_supplementary_analysis.py --corpus $C \
    --candidates $D/suspicious_unlabeled_cj_candidates.txt --json $D/supplementary.json
.venv/bin/python analysis_output/jm_connectivity_analysis.py --corpus $C \
    --candidates $D/suspicious_unlabeled_cj_candidates.txt --out $D \
    --mode candidates --min-amount 1.0 --export
.venv/bin/python analysis_output/verify_disjoint.py --corpus $C \
    --candidates $D/suspicious_unlabeled_cj_candidates.txt
```

`jm_supplementary_analysis.py` is new. It covers figures in FINDINGS that no committed
script produced (§1, §3, the §4 amount columns, §5, §8.1, H1). On the old corpus it
reproduces §1, §3, §4 and §5 exactly. It reproduces §8.1 and H1 to within ±1–2 units:
p50 37 vs 36 txs, H1 37/34 vs 38/35.
