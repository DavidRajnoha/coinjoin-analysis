# JoinMarket remix behaviour and the single-taker leak

**A measurement study of CoinJoin output reuse on Bitcoin mainnet, 2015–2025, with an
assessment of what it implies for taker anonymity.**

Status: analysis complete; the central conditional probability is **not yet measured**
and requires the emulation described in §8. Every figure below is reproducible from the
scripts in §9.

---

## Executive summary

Between 32.9% and ~61% of JoinMarket CoinJoin outputs are respent into another CoinJoin.
The uncertainty is not statistical noise — it is the size of a demonstrated gap in the
labeled dataset.

Three findings matter beyond the headline rate:

1. **Reuse rises steeply with transaction value** — 3.5% for sub-0.01 BTC CoinJoins,
   54.5% above 20 BTC. Connectivity follows: 80.1% of ≥10 BTC CoinJoins have at most one
   output whose destination is unaccounted for.
2. **Denser traffic correlates with *weaker* anonymity**, not stronger. Within a given
   year, busier months show higher connectivity (r = +0.65). More activity places more of
   each coin's onward path inside the observable set.
3. **A recurring structural pattern** — every mixed output traced onward except exactly
   one — occurs in 39.3% of ≥1 BTC CoinJoins and has been stable for a decade. Whether
   that lone output belongs to the taker is the open question; the pattern's *frequency*
   is established, its *precision* is not.

The apparent collapse of remixing in 2022–23 (to 13–14%) is largely an artifact of two
confounds: a shift in the amount mix toward small denominations, and incomplete labeling.
Conditioned on ≥1 BTC, the signal is flat across 2015–2021.

---

## 1. Data and its limits

| dataset | scale | provides | cannot provide |
|---|---|---|---|
| **Mainnet corpus**<br>`data/joinmarket/real-data/coinjoin_tx_info.json` | 24,135 labeled CoinJoins<br>279,165 outputs / 335,408 inputs<br>2015-01-02 → 2025-11-28 | real behaviour, amounts, timing; 98.9% of outputs have a recorded spender | **no role attribution** — `wallet_name` is uniformly `real_unknown`; maker and taker are indistinguishable |
| **Whitebox emulation**<br>`data/joinmarket/**/whitebox_cj_objs.pkl` | 84 runs, ~38k maker outputs | complete ground truth: every wallet, UTXO and role known | window ≈980 blocks vs ≈355-block mean reuse delay — the rate never stabilises |

51.9% of corpus outputs are standard-denomination ("mixed"); median 6 mixed outputs per
transaction (p10 = 3, p90 = 10).

> **The central constraint.** Mainnet has the behaviour but no roles. Emulation has the
> roles but too short a horizon. **No available dataset has both.** Every claim about
> *takers specifically* is therefore inference, not measurement — which is precisely
> what §8 is designed to fix.

---

## 2. Remix rate

### 2.1 Headline

- **32.9%** of outputs are respent into another *labeled* CoinJoin — a **lower bound**.
- **~61%** counting structurally-verified candidates (§6).
- The rate **converges**: 31.5% at 30 days, 32.9% at 90, 33.5% at 180, 34.3% at 365.
  Remixing that happens, happens within ~90 days.

### 2.2 Fate of every output

| fate | count | share |
|---|---|---|
| respent into a **known** CoinJoin | 91,865 | 32.9% |
| respent into a **candidate** CoinJoin | 79,309 | 28.4% |
| respent **outside** the observable set | 104,906 | 37.6% |
| never spent / no spender recorded | 3,085 | 1.1% |

### 2.3 The upper bound is threshold-dependent

A candidate is an external transaction absorbing outputs from ≥N distinct CoinJoins.
N is a judgement call, and the bound moves with it:

| N | external txs | outputs absorbed | upper bound |
|---|---|---|---|
| 2 | 33,165 | 117,641 | 75.0% |
| **3** | **15,926** | **79,309** | **61.3%** |
| 4 | 8,356 | 54,183 | 52.3% |
| 5 | 4,830 | 38,573 | 46.7% |
| 8 | 1,260 | 16,465 | 38.8% |
| 20 | 107 | 3,474 | 34.2% |

**Treat 61.3% as a reasoned estimate, not a measurement.** N≥8 nearly collapses onto
the measured rate.

---

## 3. Value is the dominant covariate

Remix rate by CoinJoin amount (all years pooled, 90-day window):

| amount | transactions | outputs | remix rate |
|---|---|---|---|
| <0.01 BTC | 924 | 5,344 | **3.5%** |
| 0.01–0.1 | 1,977 | 14,870 | 9.9% |
| 0.1–0.5 | 3,007 | 22,265 | 15.5% |
| 0.5–1 | 2,023 | 12,244 | 32.2% |
| 1–5 | 6,777 | 38,269 | 42.7% |
| 5–20 | 7,320 | 39,915 | **53.7%** |
| >20 | 1,814 | 9,077 | **54.5%** |

A ~15× spread. Two readings, not separable with this data: small outputs sit near the
dust/fee threshold where remixing is uneconomic (**behavioural**), and small CoinJoins
are harder to detect so their successors go unlabeled (**artifact**). The
"spent-outside" share reaches 94.3% in the smallest bucket, which is consistent with
both.

> **Why this reframes the 2022–23 collapse.** Those years moved 50–53% of transactions
> into the 0.1–0.5 BTC bucket, against 1–4% in 2017–19. The headline remix decline is
> therefore substantially a change in *what was being mixed*, not in *whether people
> remixed*. Two independent checks argue against a behavioural reading: never-spent
> outputs stay at ~1% through the trough, and median time-to-remix stays at ~0.5 days —
> coins kept moving at the same pace.

---

## 4. Connectivity and the all-but-one pattern

For each transaction: how many of its mixed outputs are traced onward to a JoinMarket
transaction, and how many of its inputs came from one? Candidates counted as JoinMarket.

| metric | all amounts | **≥1 BTC** | ≥5 BTC | ≥10 BTC |
|---|---|---|---|---|
| n | 24,135 | **15,935** | 9,139 | 5,030 |
| output: all traced | 26.6% | **35.7%** | 39.1% | 38.0% |
| output: all but one | 32.0% | **39.3%** | 40.5% | 42.1% |
| **output: all + all-but-one** | 58.5% | **75.0%** | 79.6% | **80.1%** |
| input: all traced | 15.2% | 20.5% | 24.0% | 25.4% |
| input: all but one | 13.8% | 17.8% | 19.2% | 20.4% |
| both sides fully traced | 6.7% | 9.2% | 10.7% | 10.9% |
| **both sides all-but-one** | 5.7% | **7.4%** | 8.1% | **8.8%** |

*The ≥5 and ≥10 BTC columns are nested subsets of ≥1 BTC, so part of the monotone rise
reflects a shrinking, self-selected population.*

**The tail collapses at value.** Transactions with 5+ unexplained outputs fall from
11.1% (all amounts) to 1.5% (≥1 BTC). Large CoinJoins are almost never opaque — their
mass sits entirely at zero or one unexplained output.

**The input side is the binding constraint.** 29.9% of ≥1 BTC transactions still have 5+
unexplained inputs, versus 1.5% on the output side. Makers fund from outside the system
continuously, so "all inputs from JoinMarket" is intrinsically rarer.

### 4.1 Per-year, ≥1 BTC

| year | txs | out all | out abo | out a+abo | in all | in abo | both all | both abo |
|---|---|---|---|---|---|---|---|---|
| 2015 | 956 | 25.8% | 37.1% | 63.0% | 12.2% | 16.2% | 4.5% | 7.1% |
| 2016 | 4,347 | 36.2% | 40.6% | 76.8% | 19.6% | 16.3% | 9.5% | 7.0% |
| 2017 | 2,902 | 43.6% | 39.2% | **82.8%** | 24.6% | 19.6% | **12.6%** | 7.6% |
| 2018 | 1,725 | 41.2% | 38.1% | 79.2% | 24.2% | 19.2% | 12.5% | 7.5% |
| 2019 | 2,390 | 39.9% | 40.0% | 79.9% | 24.0% | 17.4% | 10.5% | 7.2% |
| 2020 | 899 | 28.3% | 37.6% | 65.9% | 13.9% | 15.5% | 4.6% | 6.3% |
| 2021 | 675 | 34.5% | 34.2% | 68.7% | 20.1% | 18.2% | 9.2% | 7.3% |
| 2022 | 197 | 18.3% | 33.0% | 51.3% | 6.6% | 9.1% | 2.0% | 4.1% |
| 2023 † | 152 | 3.3% | 24.3% | 27.6% | 0.0% | 3.9% | 0.0% | 1.3% |
| 2024 | 1,589 | 25.4% | 44.6% | 70.0% | 19.9% | 22.8% | 4.7% | **10.2%** |
| 2025 † | 103 | 1.9% | 12.6% | 14.6% | 1.9% | 1.9% | 0.0% | 1.0% |

† Thin and heavily right-censored. `in all` = 0.0% is the signature of a population too
recent to have resolved. **Exclude from any trend claim.**

**`both abo` holds at 6.3–7.6% across 2015–2021** and peaks at 10.2% in 2024. Filtering
by amount removes nearly all the volatility of the unfiltered series.

*Caveat on 2024:* its `out all` (25.4%) is **lower** than 2017's (43.6%) while `both abo`
is higher — the peak comes from more transactions landing at exactly-one-unexplained,
not from better overall connectivity.

---

## 5. Traffic density reduces anonymity

Monthly resolution, ≥1 BTC, months with n≥30 (83 months; median 134 tx/month,
range 35–861):

| correlation with monthly transaction count | raw | **within-year deviations** |
|---|---|---|
| output: all traced | +0.42 | **+0.59** |
| output: all + all-but-one | +0.50 | **+0.65** |
| both sides all-but-one | +0.31 | **+0.39** |

The within-year column compares each month against its own year's mean, removing
secular drift — and the correlations get **stronger**. A busy month leaks more than a
quiet month *in the same year*.

**Mechanism:** denser traffic puts more of each coin's onward path inside the observable
window, leaving fewer outputs unaccounted for.

> **Competing explanation, not excluded.** Traffic volume and labeling quality are
> entangled: busier periods may simply be better-detected periods. The within-year
> control weakens this but does not eliminate it. Of all findings here, this is the one
> most dependent on obtaining a complete transaction set (§6).

---

## 6. The dataset is incomplete — with structural evidence

15,926 external transactions each absorb outputs from ≥3 distinct CoinJoins, a
convergence pattern ordinary spending does not produce. They hold 28.4% of all corpus
outputs, and the set is **66% the size of the labeled corpus** (15,926 / 24,135).

**Structural verification** against mempool.space, testing the JoinMarket shape
(n≥3 equal-valued outputs, n or n−1 change outputs, ≥n inputs):

| group | conforming | what it is |
|---|---|---|
| **Candidates** (≥3 sources) | **92/100** | the suspicious pool |
| Single-source external txs | 51/100 | *not a baseline* — see below |
| **Random chain transactions** | **0/100** | the true base rate |

The random sample spanned block heights 338,198–870,305 with median 1 input / 2 outputs;
**not one had even 3 equal-valued outputs.** The gap is therefore **+92 pp**, and the
rule essentially never fires on ordinary traffic.

The 8 non-conforming candidates are exactly what should fail: seven are consolidations
(262, 585, 417, 131 inputs → a single output).

**Missing labels are iterative, not a single slice.** The single-source pool conforming
at 51% against a 0% base rate means a second layer of unlabeled CoinJoins sits behind
the first. This compounds — each undetected CoinJoin also removes its successors from
the labeled set.

> **This does not raise the remix estimate.** Relabeling a candidate does not merely
> move outputs from "outside" to "remixed": each newly labeled CoinJoin contributes its
> own inputs to attribute and its own outputs to the denominator. Numerator and
> denominator grow together. **~61% stands.** What incompleteness explains is the
> *apparent* year-to-year volatility.

---

## 7. Hypothesis assessment

| # | hypothesis | verdict | strongest evidence | what would settle it |
|---|---|---|---|---|
| **H1** | All-but-one output ⇒ taker exiting | **Plausible, unproven** | 39.3% of ≥1 BTC txs; all-but-one resolves on the *same* timescale as fully-mixed (median 35 vs 38 intervening txs), so not merely slow txs caught mid-flight | §8 emulation |
| **H2** | Both-sides all-but-one ⇒ single taker | **Plausible, unproven** | 7.4% of ≥1 BTC (8.8% at ≥10 BTC); stable 6.3–7.6% for 2015–2021 | §8 emulation |
| **H3** | Sudoku + chain construction closes the loop | **Coherent, untested** | Would cover 75% of ≥1 BTC transactions if it works | End-to-end run; no step executed here |
| **H4** | Higher value ⇒ easier attack | **Supported** | Monotone on every metric: remix 3.5%→54.5%, a+abo 58.5%→80.1%, both abo 5.7%→8.8% | — |
| **H5** | More traffic ⇒ lower anonymity | **Supported** | Within-year r = +0.65, stronger than raw — not secular drift | Complete tx set, to exclude the coverage confound |
| **H6** | Corpus incomplete | **Supported** | 92/100 vs 0/100 structural; candidate set 66% of corpus size | — |

### Not established

1. **P(output is the taker's | all-but-one)** — the core conditional for H1 and H2.
2. **H3 end-to-end** — the sudoku + chain composition was never run.
3. **Maker-specific reuse on mainnet** — impossible without role labels.
4. **That candidates are truly CoinJoins** — 92% structural conformance is strong but
   not proof; consolidation can imitate the shape.
5. **Whether H5 is behaviour or coverage.**

---

## 8. Proposed emulation

**Objective:** measure `P(the unexplained output is the taker's | all-but-one pattern)`
against ground truth, reported **against the random-guess baseline of 1/n**. If
precision does not clearly exceed that baseline, the mainnet frequencies in §4 are not
evidence of a leak.

**Existing runs cannot answer this** — verified, not assumed. In `final-3` the
unexplained-output distribution is piled at 8+ and never reaches 1, giving **zero**
all-but-one transactions. Runs are also only ~10.7% takers.

| parameter | value | rationale |
|---|---|---|
| horizon | 6,000+ blocks | vs the usual 1,000; mean reuse delay ≈355 blocks, so ~17 reuse generations |
| burn-in / cool-down | excluded at evaluation | edge transactions produce spurious "unexplained" outputs from censoring, not behaviour |
| **cool-down target** | **~290 intervening JM txs** | 90% retention (§8.1) |
| population sweep | 20/40/80 makers × 4/8/16 takers | maker:taker ratio is the variable expected to drive the leak |
| control arm | 4 tumblers, plus a no-tumbler run | separates deep-chain effects from ordinary-taker effects |
| funding | target ≥1 BTC CoinJoin amounts | matches the population where the signal lives (§3) |

### 8.1 Calibration: lag until all outputs are remixed

| unit | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|
| days | 2.5 | 9.2 | 29.7 | 59.0 | 160.7 |
| **intervening JM txs** | **36** | **104** | **288** | **511** | **1,911** |

Use the transaction-count row: it is invariant to how fast tumblers are driven, and so
transfers directly between mainnet and emulation. Cumulatively, 58.4% resolve within 50
intervening transactions, 74.3% within 100, 94.9% within 500.

*Caveats:* corpus `block_index` is an in-block index, not a height, so day→block
conversion uses a 144/day approximation. Lags to candidates are untimestamped and
excluded, truncating the tail.

---

## 9. Reproducing this

| script | produces |
|---|---|
| `mainnet_remix_analysis.py` | §2 remix rates, fate split, threshold sensitivity |
| `jm_connectivity_analysis.py --min-amount 1.0` | §4 connectivity, both sides, per-year |
| `verify_candidates_via_api.py` | §6 structural check (mempool.space / blockstream) |
| `random_chain_baseline.py` | §6 true base rate (0/100) |
| `verify_disjoint.py` | invariants on the candidate set (4 checks, all pass) |
| `simulate_single_taker_leak.py` | §8 scenario generation + ground-truth evaluator |
| `joinmarket/common/maker_utxo_reuse.py` | whitebox maker reuse metric (19 tests) |

**Data artifacts:** `suspicious_unlabeled_cj_candidates.{txt,csv}` (15,926 candidates
with source counts for re-thresholding), `both_sides_all_but_one.txt` (1,367 leak-signal
txids), `candidate_structural_check.json`, `random_chain_baseline.json`.

**Whitebox note.** The maker reuse metric is deliberately *not* wired into the unified
report: reuse is a structural property of the simulation, not an attribution result, and
presenting it there would imply the attack recovered it. Cite `reuse_by_age()` rather
than a point estimate — the censored rate climbs monotonically (20.7% → 38.9%) with the
censoring horizon and has no stable value.
