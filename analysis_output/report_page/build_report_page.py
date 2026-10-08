"""
Build the HTML report page (JoinMarket Remix Atlas 2026) from the committed result files.

Reads the remix reports and supplementary.json of analysis_output/2026 (delivered corpus) and
analysis_output/2026_augmented (main results), plus 2026/hidden_by_halfyear.json, and injects
them into template.html. Figures quoted from FINDINGS.md (2025 corpus) and Moser & Bohme
(WEIS 2016) are written into the template itself.

Run: python analysis_output/report_page/build_report_page.py [--out FILE]
"""
import argparse
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
AO = os.path.dirname(HERE)


def remix_report(path):
    """Parse the text report of mainnet_remix_analysis.py."""
    t = open(path).read()
    sec = lambda a, b: t.split(a)[1].split(b)[0]
    ages = [{'age': int(a), 'rate': float(r)} for a, _, _, r in
            re.findall(r'^\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%$', sec('2. REMIX', '3. PER-YEAR'), re.M)]
    per_year = {y: float(r) for y, _, _, r in
                re.findall(r'^\s+(20\d\d)\s+(\d+)\s+(\d+)\s+([\d.]+)%$', sec('3. PER-YEAR', '4. FATE'), re.M)}
    fate = {}
    for line in sec('6. PER-YEAR FATE SPLIT', '7. EXPORT').splitlines():
        m = re.match(r'\s+(20\d\d)\s+(\d+)\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)%', line)
        if m:
            fate[m[1]] = {'n': int(m[2]), 'known': float(m[3]), 'cand': float(m[4]),
                          'outside': float(m[5]), 'never': float(m[6])}
    thresholds = [{'n': int(a), 'ext': int(b), 'out': int(c), 'ub': float(e)} for a, b, c, d, e in
                  re.findall(r'^\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%\s+([\d.]+)%$',
                             sec('5. SENSITIVITY', '6. PER-YEAR'), re.M)]
    return {'ages': ages, 'per_year': per_year, 'fate': fate, 'thresholds': thresholds}


def result_set(folder):
    supp = json.load(open(os.path.join(AO, folder, 'supplementary.json')))
    return {'remix': remix_report(os.path.join(AO, folder, 'remix_report.txt')),
            'supp': {k: supp[k] for k in ('s3', 's4', 's4_years_ge1', 's8_1')}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(HERE, 'joinmarket_remix_atlas.html'))
    args = ap.parse_args()

    hidden = json.load(open(os.path.join(AO, '2026', 'hidden_by_halfyear.json')))['rows']
    data = {'aug': result_set('2026_augmented'), 'dlv': result_set('2026'),
            'hidden_halfyear': [{'p': r['period'], 'hidden': r['hidden'], 'corpus': r['labeled']}
                                for r in hidden]}
    page = open(os.path.join(HERE, 'template.html')).read()
    assert '/*DATA*/null' in page, 'template has no data placeholder'
    with open(args.out, 'w') as fh:
        fh.write(page.replace('/*DATA*/null', json.dumps(data, separators=(',', ':'))))
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
