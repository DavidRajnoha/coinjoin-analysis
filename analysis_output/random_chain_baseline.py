"""True random-chain baseline: sample real blocks, then random txs from them.

The earlier 'control' group was sampled from external txs fed by exactly ONE corpus
coinjoin -- i.e. direct descendants of known JoinMarket activity, which is exactly
where unlabeled coinjoins would concentrate. That is not a base rate. This samples
transactions from the chain at large instead.

Blocks are drawn from the same era as the corpus (2015-2025) so the comparison is
era-matched rather than dominated by modern transaction patterns.
"""
import json, random, sys, time, urllib.request, urllib.error, collections
sys.path.insert(0,'analysis_output')
src=open('analysis_output/verify_candidates_via_api.py').read()
exec(src.split('def main()')[0])   # reuse evaluate_tx, fetch_tx, shape, ENDPOINTS

rng=random.Random(int(sys.argv[1]) if len(sys.argv)>1 else 0)
N=int(sys.argv[2]) if len(sys.argv)>2 else 100

def get(url):
    for a in range(4):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'CJ-Research/1.0'})
            with urllib.request.urlopen(req,timeout=30) as r: return r.read().decode()
        except Exception: time.sleep(0.8*(2**a))
    return None

# Corpus era: block heights roughly 337000 (Jan 2015) .. 875000 (Nov 2025)
LO,HI=337000,875000
results=[]
seen_blocks=set()
while len(results)<N:
    h=rng.randint(LO,HI)
    if h in seen_blocks: continue
    seen_blocks.add(h)
    bh=get(f"https://mempool.space/api/block-height/{h}")
    if not bh: continue
    bh=bh.strip()
    txt=get(f"https://mempool.space/api/block/{bh}/txids")
    if not txt: continue
    try: txids=json.loads(txt)
    except Exception: continue
    if len(txids)<2: continue
    # skip coinbase (index 0)
    pick=rng.choice(txids[1:])
    tx=fetch_tx(pick)
    time.sleep(0.5)
    if tx is None: continue
    ic,vals=shape(tx)
    ok,det=evaluate_tx(ic,vals)
    det['txid']=pick; det['height']=h
    results.append(det)
    if len(results)%10==0: print(f"  {len(results)}/{N}",flush=True)

ok=[r for r in results if r['status']=='CONFORMS']
print(f"\nRANDOM CHAIN BASELINE: {len(ok)}/{len(results)} conform ({len(ok)/len(results)*100:.0f}%)")
if ok:
    print("  by n:",dict(sorted(collections.Counter(r['n'] for r in ok).items())))
    ins=sorted(r['inputs'] for r in ok)
    print(f"  inputs median={ins[len(ins)//2]} max={max(ins)}")
json.dump(results,open('analysis_output/random_chain_baseline.json','w'),indent=2)
print("  wrote analysis_output/random_chain_baseline.json")
