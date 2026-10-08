# JoinMarket remix behaviour and the single-taker leak: 2026 corpus

**The FINDINGS.md measurements rerun on the 2026 Dumplings rescan (with the D5 fix), after
recovering ~19.7k JoinMarket coinjoins that the pipeline had filed as post-mix.**

Status: measurements complete on the augmented corpus. The structural API check (§6) was
not rerun. The central conditional probability (§8) is still unmeasured. Compared with
FINDINGS.md, several conclusions **reverse**: they are flagged ⚠ below.

---

## Executive summary

**84.6% of JoinMarket CoinJoin outputs are respent into another labeled CoinJoin. The
upper bound is 93.1%.** The 2025 corpus gave 32.9%–61%. Almost all of the difference is
detection coverage, not behaviour.

1. **Remixing is flat over time.** Per-year 90-day rates sit at 78–90% in every year,
   2015–2026. ⚠ The 2022–23 "collapse" was a detection artifact. It came from Dumplings'
   protocol precedence (§1.2), not from a shift in the amount mix.
2. **⚠ Value is only a weak covariate.** Remix rises from 66% (<0.01 BTC) to 83% (1–5 BTC),
   then falls above 20 BTC (71%). The old ~15× spread was mostly under-labeling of small
   coinjoins.
3. **The all-but-one pattern is near-universal at ≥1 BTC.** 95.0% of ≥1 BTC CoinJoins have
   at most one untraced mixed output. The both-sides all-but-one signal holds 8.5% of them
   (3,502 txids). Its rate is roughly the same as before (7.4%). ⚠ It is no longer stable
   over time: 3.6–11.6% in 2015–21 and 16–23% in 2023–25.
4. **⚠ Traffic density no longer predicts weaker anonymity.** The within-year correlation
   fell from +0.65 to +0.24. For the both-sides signal it is negative (−0.18). FINDINGS.md
   flagged this as the result most exposed to labeling; it did not survive.
5. **Remixing is slower in transaction terms than the old calibration implied.** Full
   resolution takes a median of 574 intervening JoinMarket txs, and 4,478 at p90, against
   36 / 288. That is 8.5 / 91 days, against 2.5 / 30. The emulation horizon in §8 must
   grow accordingly.

---

## 1. Data and its limits

### 1.1 Corpus

| | FINDINGS.md | 2026 as delivered | **2026 augmented (used here)** |
|---|---|---|---|
| file | `real-data/coinjoin_tx_info.json` | `real-data-2026/coinjoin_tx_info.json` | `real-data-2026/coinjoin_tx_info_augmented.json` |
| labeled coinjoins | 24,135 | 156,352 | **176,086** |
| span | 2015-01-02 → 2025-11-28 | 2015-01-02 → 2026-10-05 | same |
| outputs | 279,165 | 1,835,657 | 2,170,283 |
| with a recorded spender | 98.9% | 98.6% | 97.2% (see §1.4) |
| mixed share / median mixed per tx | 51.9% / 6 | 51.6% / 6 | 51.6% / 6 (p10 3, p90 10) |

Role attribution is still absent (`wallet_name` = `real_unknown`). Every figure here is
remixing by *any* participant.

### 1.2 Pipeline issue: Wasabi 1 precedence hides JoinMarket coinjoins

- **The Wasabi 1 rule.** From block 610,000, Dumplings labels as Wasabi 1 any tx that is
  all native SegWit, has ≥10 equal outputs at 0.08–0.12 BTC, has ≥n inputs, and has ≥2
  unique outputs. That check runs before the JoinMarket rule. JoinMarket moved to native
  SegWit around the start of 2021, and its large ~0.1 BTC coinjoins match the rule (2,144 in this data).
- **Demotion of their children.** A tx that spends such an output gets
  `isOtherCj = false` (`Scanner.cs`). It lands in `OtherCoinJoinPostMixTxs.txt`.
- **Partial restore.** `parse_dumplings.restore_false_positives_for_others` moves the
  mislabeled parents back into the JoinMarket set (2,140 are in the delivered corpus). It
  copies their children only as post-mix records and never re-evaluates them.

**Evidence.**

| | 2021+ missed candidates | 2021+ labeled corpus | pre-2021 missed candidates |
|---|---|---|---|
| has a Wasabi 1-shaped parent | **97.1%** | 3.2% | 4.3% |
| RBF-signalling | 2% | 92% | 96% |

The candidate-to-corpus ratio by half-year confirms the onset: about 0.01 through 2020,
then 0.14–0.84 from 2021. The Wasabi 1-shaped parents are 100% non-RBF, so this is
probably one specific client population. That is an association, not a tested cause.

**Fix applied here** (`augment_corpus.py`). Promote every post-mix tx that passes all of
the following:
- the patched Dumplings rule (D5 allowance, n≥3, or ≥2 JoinMarket parents);
- the BASIC `parse_dumplings` checks the corpus itself went through (in/out ≤4, ≤100
  in/outs, reuse ≤0.34, no OP_RETURN, no `fp_reason`);
- it is not itself Wasabi 1/2- or Samourai-shaped.

This is iterated to a fixed point: 19,732 txs in round 1, 2 in round 2, 0 in round 3.
**19,734 were promoted**, all from 2020 or later (2021: 1.4k; 2022–26: 3.3–4.3k per year).

### 1.3 Pipeline issue: 3–4 party coinjoins are tagged but not removed

43,798 delivered coinjoins (28%) carry `fp_reason: MIN_SAME_VALUES_THRESHOLD` but still
sit in the `coinjoins` section. Every one has exactly 3 or 4 equal outputs, i.e. a taker
plus 2 or 3 makers. The tagged share is 74% in 2015 and 51% in 2016, against 3–6% from
2021 on. The tag implies the upstream check ran with a threshold of 5 (inferred from the
data, not from a config).

**They are genuine JoinMarket coinjoins: early JoinMarket's default was 2 makers.**
Möser & Böhme, *Join Me on a Market for Anonymity* (WEIS 2016), traced 8,648 JoinMarket
transactions from June 2015 to January 2016 (blocks 358,000–396,048). Their Fig. 5 gives
the number of makers chosen (default = 2). Over the same window:

| makers | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10+ | total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| paper | 184 | 4,734 | 1,783 | 1,066 | 624 | 163 | 54 | 20 | 12 | 8 | 8,648 |
| corpus | 0 | 4,674 | 1,778 | 1,229 | 663 | 164 | 117 | 30 | 13 | 5 | 8,673 |

- **The tagged transactions are exactly the 2- and 3-maker rows:** 74.4% of the corpus
  window against 75.4% in the paper.
- **The two sources agree nearly exactly** on these rows, from fully independent data.

A minimum of 5 equal outputs would discard three quarters of JoinMarket's first year.
**They are kept in the main numbers.** §10 reports the variant without them only as a
sensitivity check.

**Remaining gap: 1-maker coinjoins** (2 equal outputs; 2.1% in the paper) are absent from
the corpus. The patched Dumplings rule requires n≥3, which excludes them.

### 1.4 Known gaps that remain

- **Hidden coinjoins two or more hops away.** A JoinMarket coinjoin whose JoinMarket
  parents were all hidden never reached the file at all. 38,621 outputs of the promoted
  txs have no recorded spender. In an API sample of 200, 20% went into JoinMarket-shaped
  transactions absent from the file. Weighted by how many hidden outputs each absorbs,
  that is **~500–800 distinct transactions** (~530 if the in/out ≤4 rule applies). Closing
  this needs spend lookups (mempool.space overnight, or an indexer on a full node) or a
  Dumplings rescan with the precedence fix.
- **Inflated "never spent" share.** Post-mix records only carry a spender link when the
  spender is in the file. About 11% of promoted outputs therefore read as "never spent"
  (2.8% overall, against 1.4% before augmentation). This slightly *understates* remix
  rates for 2021+.

---

## 2. Remix rate

### 2.1 Headline

- **84.6%** of outputs are respent into a labeled CoinJoin (lower bound).
- **93.1%** counting candidates (upper bound). The gap between the bounds shrank from
  28 pp to 8.5 pp.
- **The rate has not fully converged.** The spread over the last three ages is 2.0 pp:

| age | FINDINGS.md | 2026 delivered | **2026 augmented** |
|---|---|---|---|
| 30 d | 31.5% | 68.6% | **77.9%** |
| 90 d | 32.9% | 72.3% | **82.6%** |
| 180 d | 33.5% | 73.6% | **83.9%** |
| 365 d | 34.3% | 75.2% | **84.6%** |

Shorter ages on the augmented corpus: 44.0% at 1 d, 57.5% at 3 d, 66.5% at 7 d, 72.7% at
14 d.

### 2.2 Fate of every output

| fate | count | share | FINDINGS.md |
|---|---|---|---|
| respent into a **known** CoinJoin | 1,834,987 | **84.6%** | 32.9% |
| respent into a **candidate** CoinJoin | 185,148 | 8.5% | 28.4% |
| respent **outside** the observable set | 90,410 | 4.2% | 37.6% |
| never spent / no spender recorded | 59,738 | 2.8% | 1.1% |

### 2.3 Threshold sensitivity of the upper bound

| N | external txs | outputs absorbed | upper bound |
|---|---|---|---|
| 2 | 18,458 | 200,019 | 93.8% |
| **3** | **11,661** | **185,148** | **93.1%** |
| 4 | 8,734 | 175,709 | 92.6% |
| 5 | 6,964 | 168,070 | 92.3% |
| 8 | 4,482 | 152,538 | 91.6% |
| 12 | 3,077 | 138,485 | 90.9% |
| 20 | 2,032 | 122,018 | 90.2% |

The bound now moves by less than 4 pp across all thresholds. In FINDINGS.md it moved from
75% to 34%.

### 2.4 Per year (equal 90-day window)

| year | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| remix rate | 79.7% | 85.7% | 81.5% | 85.5% | 89.5% | 82.2% | 79.9% | **79.5%** | **78.4%** | 82.9% | 79.3% | 81.8% |
| *delivered corpus* | *79.7%* | *85.7%* | *81.5%* | *85.5%* | *89.5%* | *81.6%* | *64.2%* | *45.1%* | *47.6%* | *64.6%* | *52.0%* | *47.7%* |

⚠ **The 2022–23 dip is gone.** In the delivered corpus it was 45–48%. Recovering the
Wasabi-shadowed coinjoins removes it entirely. The "change in what was being mixed"
explanation in FINDINGS.md §3 is no longer needed.

---

## 3. Value dependence

Remix rate by CoinJoin amount (median mixed output), 90-day window:

| amount | txs | outputs | **remix rate** | not in corpus | FINDINGS.md rate |
|---|---|---|---|---|---|
| <0.01 BTC | 23,782 | 157,096 | **66.4%** | 22.3% | 3.5% |
| 0.01–0.1 | 49,625 | 339,838 | 76.5% | 17.2% | 9.9% |
| 0.1–0.5 | 41,943 | 274,395 | 80.5% | 14.9% | 15.5% |
| 0.5–1 | 17,174 | 103,970 | 81.0% | 15.5% | 32.2% |
| 1–5 | 26,326 | 147,325 | **83.1%** | 14.4% | 42.7% |
| 5–20 | 12,048 | 63,629 | 82.2% | 16.2% | 53.7% |
| >20 | 2,519 | 12,092 | **71.3%** | 26.9% | 54.5% |

⚠ The spread is ~1.25×, not ~15×. The rate rises up to ~1 BTC, is flat to 20 BTC, and
drops above. The dust/fee economics reading still fits the bottom bucket. Most of the
old gradient was smaller CoinJoins being under-detected.

**The amount mix still shifts.** Sub-0.5 BTC CoinJoins make up 42–70% of 2015–2021, then
83–91% of 2022–23 and 2025–26 (65% in 2024). The flat per-year rate shows this shift no longer moves the headline.

---

## 4. Connectivity and the all-but-one pattern

Candidates count as JoinMarket. Mixed outputs only.

| metric | all amounts | **≥1 BTC** | ≥5 BTC | ≥10 BTC | ≥1 BTC in FINDINGS.md |
|---|---|---|---|---|---|
| n | 176,086 | **40,973** | 14,576 | 7,264 | 15,935 |
| output: all traced | 57.0% | **59.1%** | 58.4% | 54.7% | 35.7% |
| output: all but one | 33.5% | **35.9%** | 36.5% | 39.2% | 39.3% |
| **output: all + all-but-one** | 90.5% | **95.0%** | 94.9% | 93.9% | 75.0% |
| input: all traced | 64.6% | 63.0% | 64.4% | 61.8% | 20.5% |
| input: all but one | 21.8% | 21.2% | 19.5% | 21.4% | 17.8% |
| both sides fully traced | 40.4% | 40.0% | 37.7% | 33.1% | 9.2% |
| **both sides all-but-one** | 8.8% | **8.5%** | 6.7% | 7.5% | 7.4% |
| 5+ unexplained outputs | 1.4% | 0.4% | 0.6% | 1.2% | 1.5% |
| 5+ unexplained inputs | 3.1% | 3.7% | 4.2% | 4.0% | 29.9% |

- The leak-signal set is `2026_augmented/both_sides_all_but_one.txt`: **3,502 txids** at
  ≥1 BTC, up from 1,367.
- ⚠ **Higher value no longer means more connectivity.** Every metric is flat or falls above
  1 BTC.
- ⚠ **The input side is no longer the binding constraint.** Opaque inputs (5+
  unexplained) fell from 29.9% to 3.7%.

### 4.1 Per year, ≥1 BTC

| year | txs | out all | out abo | out a+abo | in all | in abo | both all | both abo |
|---|---|---|---|---|---|---|---|---|
| 2015 | 2,419 | 61.7% | 34.6% | 96.2% | 63.3% | 22.8% | 42.9% | 9.5% |
| 2016 | 10,267 | 61.7% | 36.8% | 98.5% | 63.5% | 19.9% | 42.0% | 8.0% |
| 2017 | 5,613 | 60.1% | 36.4% | 96.5% | 58.6% | 20.1% | 37.3% | 8.2% |
| 2018 | 4,649 | 70.0% | 28.3% | 98.3% | 73.0% | 15.7% | 51.8% | 4.4% |
| 2019 | 6,847 | 72.3% | 26.4% | 98.7% | 75.9% | 16.1% | 54.0% | 3.6% |
| 2020 | 3,117 | 54.9% | 39.4% | 94.3% | 61.4% | 23.5% | 34.8% | 11.6% |
| 2021 | 2,033 | 52.2% | 38.0% | 90.2% | 60.9% | 21.3% | 34.0% | 10.8% |
| 2022 | 916 | 35.4% | 51.7% | 87.1% | 53.8% | 16.7% | 22.9% | 6.9% |
| 2023 | 971 | 24.2% | 55.3% | 79.5% | 36.5% | 35.1% | 13.8% | **23.3%** |
| 2024 | 3,254 | 38.7% | 48.6% | 87.4% | 47.2% | 34.2% | 18.7% | 16.3% |
| 2025 | 528 | 28.8% | 41.1% | 69.9% | 35.6% | 35.8% | 14.4% | 16.3% |
| 2026 † | 359 | 17.8% | 35.4% | 53.2% | 38.7% | 42.1% | 6.7% | 15.3% |

† Right-censored. 2025 is partly censored too.

⚠ **"Both abo stable at 6.3–7.6% for 2015–2021" no longer holds.** It ranges from 3.6% to
11.6% over 2015–2021. From 2022 on, `both all` falls (54% → 14–23%) while `out abo` and
`in abo` rise, so the signal grows to 16–23%.

Two readings, not separated here:
- **Behavioural:** fewer remixing makers, so more single exits.
- **Coverage:** the ~500–800 hop-2 hidden coinjoins (§1.4) are concentrated in exactly
  these years, and each one leaves an "unexplained" output on its parent.

---

## 5. Traffic density

Monthly, ≥1 BTC, months with n ≥ 30: 128 months, median 222 tx/month, range 30–1,561.

| correlation with monthly tx count | raw | within-year | FINDINGS.md within-year |
|---|---|---|---|
| output: all traced | +0.62 | +0.41 | +0.59 |
| output: all + all-but-one | +0.53 | **+0.24** | +0.65 |
| both sides all-but-one | −0.33 | **−0.18** | +0.39 |

⚠ **H5 is not supported.** Busier months still trace more outputs, but the effect within
a year is weak. For the deanonymisation signal it is reversed: busier months show *fewer*
both-sides all-but-one transactions.

---

## 6. Remaining incompleteness

- **Candidates.** 11,661 candidates (≥3 sources) remain, 6.6% of the corpus, holding 8.5%
  of outputs. Before augmentation there were 30,328 (19%).
- **Not every candidate is a CoinJoin.** On the pre-augmentation set, 32% of candidates
  fail the JoinMarket shape outright: 6,979 have no equal outputs (consolidations), and
  the rest have multiple equal groups or n<3. The remaining set is enriched in such
  transactions, so **the 93.1% upper bound is generous**.
- **Hop-2 hidden coinjoins.** About 500–800 hidden coinjoins (§1.4) are not in the
  candidate set at all.
- **Not rerun:** the structural check against mempool.space (`verify_candidates_via_api.py`).
  The random-chain baseline (0/100) does not depend on the corpus.
- **Invariants:** `verify_disjoint.py` passes all 4 checks on the augmented corpus.

---

## 7. Hypothesis assessment

| # | hypothesis | FINDINGS.md | **2026 augmented** | evidence |
|---|---|---|---|---|
| H1 | All-but-one output ⇒ taker exiting | plausible, unproven | **plausible, unproven** | 35.9% of ≥1 BTC txs. It resolves on a similar timescale to fully-mixed txs: median 631 vs 574 intervening txs |
| H2 | Both-sides all-but-one ⇒ single taker | plausible, unproven | **plausible, unproven** | 8.5% of ≥1 BTC (3,502 txs). It is not stable over time (3.6–23.3% by year) |
| H3 | Sudoku + chain construction closes the loop | coherent, untested | **coherent, untested** | would cover 95.0% of ≥1 BTC txs |
| H4 | Higher value ⇒ easier attack | supported | ⚠ **not supported above ~1 BTC** | remix 83%→71%, a+abo 95.0→93.9%, both abo 8.5→7.5% |
| H5 | More traffic ⇒ lower anonymity | supported | ⚠ **not supported** | within-year r = +0.24 (a+abo), −0.18 (both abo) |
| H6 | Corpus incomplete | supported | **supported, much smaller** | candidates 6.6% of corpus; ~500–800 hop-2 hidden coinjoins; Dumplings precedence bug identified |

**Not established:** P(output is the taker's | all-but-one); H3 end-to-end; maker-specific
reuse on mainnet; whether the 2022+ rise in `both abo` is behaviour or coverage.

---

## 8. Emulation calibration

Lag until all mixed outputs are remixed (n = 100,177; lag measured to labeled spenders):

| unit | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|
| days | **8.5** | 31.4 | **90.9** | 163.7 | 367.9 |
| intervening JM txs | **574** | 1,775 | **4,478** | 8,077 | 18,939 |
| *FINDINGS.md (days / txs)* | *2.5 / 36* | *9.2 / 104* | *29.7 / 288* | *59.0 / 511* | *160.7 / 1,911* |

Cumulative resolution: 7.3% within 50 intervening txs, 14.7% within 100, 46.7% within 500.

⚠ **The cool-down target for 90% retention is ~4,500 intervening JoinMarket txs, not ~290.**

- **Why the tx count grew 15×:** the corpus is ~7× denser per unit time, so each day
  contains far more JoinMarket txs.
- **But it's not only density:** the time lag also roughly tripled.
- **Consequence:** the transaction-count unit still transfers to emulation, but §8 of
  FINDINGS.md needs a correspondingly longer horizon after burn-in.

---

## 9. Reproducing this

```
C=data/joinmarket/real-data-2026/coinjoin_tx_info.json
A=data/joinmarket/real-data-2026/coinjoin_tx_info_augmented.json; D=analysis_output/2026_augmented
.venv/bin/python analysis_output/augment_corpus.py --corpus $C --out $A      # also writes *_min5.json
.venv/bin/python analysis_output/mainnet_remix_analysis.py --corpus $A --out $D
.venv/bin/python analysis_output/jm_supplementary_analysis.py --corpus $A \
    --candidates $D/suspicious_unlabeled_cj_candidates.txt --json $D/supplementary.json
.venv/bin/python analysis_output/jm_connectivity_analysis.py --corpus $A \
    --candidates $D/suspicious_unlabeled_cj_candidates.txt --out $D --mode candidates --min-amount 1.0 --export
.venv/bin/python analysis_output/verify_disjoint.py --corpus $A --candidates $D/suspicious_unlabeled_cj_candidates.txt
```

| script | produces |
|---|---|
| `augment_corpus.py` | §1.2 promotion of Wasabi-shadowed coinjoins, plus the min-5 variant |
| `mainnet_remix_analysis.py` | §2 |
| `jm_supplementary_analysis.py` | §1, §3, §4 (amount columns), §5, §8, H1. It reproduces FINDINGS.md exactly on the old corpus, except §8 and H1, which are within ±1–2 txs |
| `jm_connectivity_analysis.py` | §4 ≥1 BTC, both-sides txid export |
| `candidate_profile_2026.py` | §1.2 / §6 candidate profile and API rule diagnostic |

Outputs:
- `analysis_output/2026_augmented/`: main results.
- `analysis_output/2026_augmented_min5/`: sensitivity variant.
- `analysis_output/2026/`: the delivered corpus without augmentation. Superseded; kept for
  the comparison.

---

## 10. Sensitivity: without the 3–4 party coinjoins

Augmented corpus minus the 43,979 `MIN_SAME_VALUES_THRESHOLD`-tagged txs (132,107
coinjoins). §1.3 shows these are genuine 2–3 maker JoinMarket coinjoins (the early
default), so this variant is a robustness check, not an alternative estimate. Dropping them turns their txs into external spenders, so part of the remix
mass moves into "candidates".

| metric | main | without 3–4 party |
|---|---|---|
| remix lower / upper bound | 84.6% / 93.1% | 77.6% / 91.3% |
| remix at 365 d (converged?) | 84.6% (2.0 pp, no) | 76.9% (1.5 pp, yes) |
| candidates (% of corpus) | 11,661 (6.6%) | 28,308 (21%) |
| remix <0.01 / 1–5 / >20 BTC | 66.4 / 83.1 / 71.3% | 62.2 / 71.2 / 59.2% |
| ≥1 BTC out a+abo / both abo | 95.0% / 8.5% | 89.1% / 9.5% |
| within-year r: a+abo / both abo | +0.24 / −0.18 | +0.41 / −0.13 |
| lag p50 / p90 (JM txs) | 574 / 4,478 | 620 / 4,659 |
| lag p50 / p90 (days) | 8.5 / 90.9 | 12.7 / 113.5 |

The qualitative conclusions hold in both variants: remix ~80%, a weak and non-monotone
value effect, a both-sides signal around 8–10%, no density effect on the signal, and a
cool-down of thousands of intervening transactions. Without the 3–4 party coinjoins,
remix *falls* with value above 0.5 BTC.
