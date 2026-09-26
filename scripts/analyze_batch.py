#!/usr/bin/env python3
"""Summarize a batch of Jev runs: outcome, furthest floor, Act 1 boss result, and
HP lost per encounter (worst offenders), optionally compared with another batch."""
import argparse, glob, json
from collections import defaultdict
from pathlib import Path
RUNS = Path(__file__).resolve().parent.parent/'docs/playtests/runs'

def load(run):
    rows = [json.loads(l) for l in (RUNS/run/'jev-decisions.jsonl').read_text().splitlines()]
    res = json.loads((RUNS/run/'result.json').read_text()) if (RUNS/run/'result.json').exists() else {}
    return rows, res

def summarize(prefix, quiet=False):
    runs = sorted(Path(p).name for p in glob.glob(str(RUNS/(prefix+'-*'))) if Path(p).is_dir())
    per_enc = defaultdict(list); table = []
    for run in runs:
        try: rows, res = load(run)
        except FileNotFoundError: continue
        decs = [r for r in rows if r.get('kind') == 'decision']
        if len(decs) < 20: table.append((run, res.get('outcome'), None, None, 'insufficient data')); continue
        g = lambda r: r['observation']['state'].get('game', r['observation']['state'])
        last = g(decs[-1]); floor = max((g(r).get('floor') or 0) for r in decs); act = max((g(r).get('act') or 1) for r in decs)
        boss_act1 = [r for r in decs if r['observation']['kind'] == 'combat' and g(r).get('act') == 1 and g(r).get('room') == 'Boss']
        a1 = 'no-boss' if not boss_act1 else ('beat' if act >= 2 else 'died')
        boss_name = boss_act1[0]['observation']['state']['enemies'][0]['creature']['name'] if boss_act1 else '-'
        # hp loss per combat floor
        fl = {}
        for r in decs:
            if r['observation']['kind'] != 'combat': continue
            st = r['observation']['state']; f = st.get('floor'); hp = st['player']['hp']
            e = fl.setdefault((st.get('act'), f), dict(first=hp, min=hp, room=st.get('room'), en=set()))
            e['min'] = min(e['min'], hp); e['en'].update(x['creature']['name'] for x in st.get('enemies') or [])
        for (ac, f), e in fl.items():
            per_enc[(e['room'], ','.join(sorted(e['en'])))].append(e['first'] - e['min'])
        cost = sum(r.get('cost_usd') or 0 for r in decs)
        table.append((run, res.get('outcome'), floor, f'act{act} a1boss={a1}({boss_name})', f'${cost:.3f}'))
    if not quiet:
        print(f'=== {prefix}')
        for t in table: print('  ', *t)
    usable = [t for t in table if t[2] is not None]
    a1beat = sum('a1boss=beat' in t[3] for t in usable)
    mean_floor = sum(t[2] for t in usable)/max(1, len(usable))
    print(f'  SUMMARY {prefix}: usable {len(usable)}/{len(table)}, Act1 boss beaten {a1beat}/{len(usable)}, mean furthest floor {mean_floor:.1f}')
    return per_enc

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('prefixes', nargs='+'); p.add_argument('--top', type=int, default=12)
    a = p.parse_args()
    encs = [summarize(x) for x in a.prefixes]
    keys = sorted(set().union(*encs), key=lambda k: -sum(encs[-1].get(k, [0])) / max(1, len(encs[-1].get(k, [1]))))
    print('\n  HP lost per encounter (mean over fights, n) — ' + ' | '.join(a.prefixes))
    rows = []
    for k in keys:
        cells = [(sum(e[k])/len(e[k]), len(e[k])) if k in e else None for e in encs]
        rows.append((max(c[0] for c in cells if c), k, cells))
    for _, k, cells in sorted(rows, key=lambda r: -r[0])[:a.top]:
        print(f'  {k[0]:7} {k[1][:48]:48} ' + ' | '.join(f'{c[0]:5.1f} (n={c[1]})' if c else '   -      ' for c in cells))

if __name__ == '__main__': main()
