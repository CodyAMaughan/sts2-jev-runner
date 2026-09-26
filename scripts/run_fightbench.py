#!/usr/bin/env python3
"""Fight-level benchmark: resume the exact recorded start of one fight (same deck,
HP, relics, potions, RNG state) from each source run, play it LIVE with the given
strategy version, and stop when the fight ends. Compares strategies on identical
starting states instead of noisy full runs. Uses the parallel runner slots."""
import argparse, json, os, queue, subprocess, sys, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT/'docs/playtests/runs'

def fight_start(run, floor):
    rows = [json.loads(l) for l in (RUNS/run/'jev-decisions.jsonl').read_text().splitlines()]
    for r in rows:
        o = r.get('observation') or {}
        if r.get('kind') == 'decision' and o.get('kind') == 'combat' and o['state'].get('floor') == floor:
            return r['decision_id']
    return None

def result(run_id):
    rows = [json.loads(l) for l in (RUNS/run_id/'jev-decisions.jsonl').read_text().splitlines()]
    decs = [r for r in rows if r.get('kind') == 'decision' and r['observation']['kind'] == 'combat']
    stop = next((r for r in rows if r.get('kind') == 'stopped'), {})
    if not decs: return dict(start_hp=None, end_hp=None, won=False, turns=0)
    first, last = decs[0]['observation']['state'], decs[-1]['observation']['state']
    won = stop.get('reason') == 'combat_complete'
    end = (stop.get('observation') or {}).get('state', {})
    end_hp = (end.get('game', end).get('player') or {}).get('hp') if won else 0
    en = [(e['creature']['name'], e['creature']['hp']) for e in last.get('enemies') or [] if e['creature']['hp'] > 0]
    return dict(start_hp=first['player']['hp'], end_hp=end_hp, won=won, turns=last.get('turn'), enemies_left=en)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag', required=True); p.add_argument('--floor', type=int, default=17)
    p.add_argument('--runs', nargs='+', required=True); p.add_argument('--strategy-version', required=True)
    p.add_argument('--character', default='ironclad'); p.add_argument('--slots', nargs='+', default=['', '2'])
    a = p.parse_args()
    work = queue.Queue(); ids = []
    for src in a.runs:
        floor = a.floor
        if '@' in src: src, floor = src.split('@'); floor = int(floor)  # run@floor picks a fight per run
        did = fight_start(src, floor)
        snap = RUNS/src/'snapshots'/f'{did}.json.gz'
        if not did or not snap.is_file(): print('skip', src, 'no snapshot for floor', a.floor); continue
        seed = json.loads((RUNS/src/'manifest.json').read_text())['seed']
        rid = f'fb-{a.tag}-{src}-f{floor}'; ids.append((src, rid)); work.put((rid, seed, snap))
    def worker(slot, port):
        while True:
            try: rid, seed, snap = work.get_nowait()
            except queue.Empty: return
            env = os.environ.copy(); env['DEALMAKER_SLOT'] = slot
            cmd = [sys.executable, str(ROOT/'scripts/run_jev.py'), '--id', rid, '--seed', seed, '--port', str(port),
                   '--character', a.character, '--strategy-version', a.strategy_version, '--snapshot-resume', str(snap),
                   '--stop-after-combat', '--no-snapshots', '--headless', '--timeout', '900']
            with (RUNS/f'.{rid}.log').open('w') as out: subprocess.run(cmd, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
            print(time.strftime('%H:%M:%S'), 'done', rid, flush=True)
    ts = [threading.Thread(target=worker, args=(s, 18765 + 10*(int(s or 1)-1))) for s in a.slots]
    for t in ts: t.start(); time.sleep(3)
    for t in ts: t.join()
    wins = 0; lost = []
    for src, rid in ids:
        try: r = result(rid)
        except FileNotFoundError: print(src, 'NO RESULT'); continue
        wins += r['won']; lost.append((r['start_hp'] or 0) - (r['end_hp'] or 0))
        print(f"{src}: start {r['start_hp']} -> {'WIN' if r['won'] else 'DEAD'} end {r['end_hp']} turns {r['turns']} left {r.get('enemies_left')}")
    print(f'SUMMARY {a.tag}: {wins}/{len(ids)} won, mean HP lost {sum(lost)/max(1,len(lost)):.1f}')

if __name__ == '__main__': main()
