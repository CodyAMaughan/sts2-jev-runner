#!/usr/bin/env python3
"""Summarize real engine telemetry. Never infer a victory from missing output."""
import argparse, collections, json
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('logs',nargs='+');p.add_argument('--output');a=p.parse_args()
reports=[]
for filename in a.logs:
    path=Path(filename);rows=[];bad=0
    for line in path.read_text().splitlines():
        try: rows.append(json.loads(line))
        except json.JSONDecodeError: bad+=1
    kinds=collections.Counter(r.get('kind') for r in rows)
    metadata=next((r['data'] for r in rows if r.get('kind')=='harness'),{})
    states=[]
    for r in rows:
        d=r.get('data',{})
        s=d.get('state') or d.get('before')
        if s: states.append(s)
        elif 'hp' in d and 'hand' in d: states.append(d)
    ends=[r['data'] for r in rows if r.get('kind')=='run_end']
    failures=[r['data'] for r in rows if r.get('kind')=='harness_failure']
    combats=[r['data'] for r in rows if r.get('kind')=='combat_end']
    drafts=[r['data'] for r in rows if r.get('kind')=='draft']
    plays=collections.Counter(r['data']['card']['title'] for r in rows if r.get('kind')=='decision')
    reports.append(dict(log=str(path),seed=metadata.get('seed'),policy=metadata.get('policy'),
        outcome=ends[-1].get('outcome') if ends else 'harness_failure' if failures else 'unconfirmed_or_in_progress',
        completed_combats=len(combats),combat_wins=sum(not c.get('dead',True) for c in combats),
        max_floor=max((s.get('floor') or 0 for s in states),default=0),
        max_strength=max((s.get('strength') or 0 for s in states),default=0),
        max_wall=max((s.get('wall') or 0 for s in states),default=0),
        turns=kinds['turn'],played_cards=dict(plays),drafts=drafts,failures=failures,
        malformed_lines=bad,last_state=states[-1] if states else None))
result=json.dumps(reports,indent=2)
if a.output:Path(a.output).write_text(result+'\n')
else:print(result)
