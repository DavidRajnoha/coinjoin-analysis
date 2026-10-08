"""
Cut a time window out of a coinjoin_tx_info.json and turn it into a blackbox run directory.

  --augment     first recover JoinMarket coinjoins that Dumplings filed as post-mix because of
                Wasabi 1 precedence (analysis_output/augment_corpus.py). Needs the 'postmix'
                section and loads the whole file into memory (~6-8x its size).
  --no-augment  stream only the 'coinjoins' section; low memory.

Writes RUN/coinjoin_tx_info.json, RUN/btc-node/block_*.json and RUN/window_summary.json.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, '/app/analysis_output')
sys.path.insert(0, '/app/scripts')


def in_window(cj, lo, hi):
    return lo <= cj['broadcast_time'][:10] <= hi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--run', required=True)
    ap.add_argument('--from', dest='lo', required=True)
    ap.add_argument('--to', dest='hi', required=True)
    ap.add_argument('--augment', action=argparse.BooleanOptionalAction, default=True)
    args = ap.parse_args()

    promoted = set()
    if args.augment:
        from augment_corpus import promote
        print(f'loading {args.input} (augment mode, whole file in memory)...', flush=True)
        with open(args.input) as fh:
            data = json.load(fh)
        cjs = data['coinjoins']
        if data.get('postmix'):
            promoted = set(promote(cjs, data['postmix']))
        else:
            print('no postmix section in input: nothing to recover, continuing without augmentation')
        window = {k: v for k, v in cjs.items() if in_window(v, args.lo, args.hi)}
        del data, cjs
    else:
        import ijson
        print(f'streaming {args.input} (no augmentation)...', flush=True)
        window = {}
        with open(args.input, 'rb') as fh:
            for k, v in ijson.kvitems(fh, 'coinjoins', use_float=True):
                if in_window(v, args.lo, args.hi):
                    window[k] = v

    os.makedirs(args.run, exist_ok=True)
    win_file = os.path.join(args.run, 'coinjoin_tx_info.json')
    with open(win_file, 'w') as fh:
        json.dump({'coinjoins': window}, fh)

    summary = {
        'input': args.input, 'from': args.lo, 'to': args.hi, 'augment': args.augment,
        'coinjoins': len(window),
        'over_25_inputs': sum(len(v['inputs']) > 25 for v in window.values()),
        'promoted_in_window': sum(k in promoted for k in window),
        'tagged_min_same': sum(v.get('fp_reason') == 'MIN_SAME_VALUES_THRESHOLD' for v in window.values()),
    }
    with open(os.path.join(args.run, 'window_summary.json'), 'w') as fh:
        json.dump(summary, fh, indent=1)
    print('window:', json.dumps(summary))

    from transform_blocksci_to_blocks import transform_blocksci_to_blocks
    transform_blocksci_to_blocks(win_file, args.run, split_by_month=False)


if __name__ == '__main__':
    main()
