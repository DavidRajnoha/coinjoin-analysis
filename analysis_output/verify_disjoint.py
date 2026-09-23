"""
Verify that the 'suspicious unlabeled coinjoin candidates' are disjoint from the
labeled corpus coinjoins.

The three-way fate split (known remix / suspicious / completely outside) is only
meaningful if no transaction can land in two buckets. By construction a candidate
is an EXTERNAL spender, i.e. one that is not itself a corpus coinjoin - this script
checks that construction actually held, rather than assuming it.

Run:  .venv/bin/python analysis_output/verify_disjoint.py
Exits non-zero if any invariant fails.
"""
import json, collections, sys, os

CORPUS = 'data/joinmarket/real-data/coinjoin_tx_info.json'
CAND = 'analysis_output/suspicious_unlabeled_cj_candidates.txt'

d = json.load(open(CORPUS))
cjs = d['coinjoins']
corpus_ids = set(cjs)
cand_ids = {l.strip() for l in open(CAND) if l.strip()}

print(f"corpus coinjoins (labeled)     : {len(corpus_ids)}")
print(f"suspicious candidates          : {len(cand_ids)}")

ok = True

# 1. No candidate may also be a labeled corpus coinjoin.
overlap = corpus_ids & cand_ids
print(f"\n[1] overlap (corpus AND candidate): {len(overlap)}")
if overlap:
    ok = False
    print("    FAIL - examples:", list(overlap)[:5])
else:
    print("    PASS - the two sets are disjoint")

# 2. Candidate file must have no duplicates.
raw = [l.strip() for l in open(CAND) if l.strip()]
print(f"\n[2] duplicate txids in file: {len(raw) - len(set(raw))}")
if len(raw) != len(set(raw)):
    ok = False
    print("    FAIL")
else:
    print("    PASS")

# 3. Re-derive candidates from the corpus and confirm the file matches exactly.
ext_src = collections.defaultdict(set)
for txid, c in cjs.items():
    for o in c['outputs'].values():
        sb = o.get('spend_by_tx')
        if not sb or not sb.startswith('vin_'):
            continue
        sp = sb.split('_')[1]
        if sp not in corpus_ids:          # external by definition
            ext_src[sp].add(txid)
rederived = {k for k, v in ext_src.items() if len(v) >= 3}
print(f"\n[3] re-derived candidates: {len(rederived)}")
print(f"    missing from file: {len(rederived - cand_ids)}, extra in file: {len(cand_ids - rederived)}")
if rederived != cand_ids:
    ok = False
    print("    FAIL")
else:
    print("    PASS - file reproduces exactly")

# 4. Every output lands in exactly one fate bucket (partition check).
tot = known = susp = outside = never = 0
for txid, c in cjs.items():
    for o in c['outputs'].values():
        tot += 1
        sb = o.get('spend_by_tx')
        if not sb or not sb.startswith('vin_'):
            never += 1
            continue
        sp = sb.split('_')[1]
        in_corpus = sp in corpus_ids
        in_cand = sp in cand_ids
        if in_corpus and in_cand:          # would be a double-count
            ok = False
        if in_corpus:
            known += 1
        elif in_cand:
            susp += 1
        else:
            outside += 1
print(f"\n[4] partition check over {tot} outputs")
print(f"    known={known}  suspicious={susp}  outside={outside}  never={never}")
print(f"    sum={known+susp+outside+never} (must equal {tot})")
if known + susp + outside + never != tot:
    ok = False
    print("    FAIL")
else:
    print("    PASS - buckets partition all outputs, no double counting")

print(f"\nRATIO: candidates / labeled corpus = {len(cand_ids)}/{len(corpus_ids)} = "
      f"{len(cand_ids)/len(corpus_ids):.3f}  ({len(cand_ids)/len(corpus_ids)*100:.1f}%)")
print(f"if ALL candidates were true coinjoins, corpus would grow to "
      f"{len(corpus_ids)+len(cand_ids)} (+{len(cand_ids)/len(corpus_ids)*100:.0f}%)")

print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
sys.exit(0 if ok else 1)
