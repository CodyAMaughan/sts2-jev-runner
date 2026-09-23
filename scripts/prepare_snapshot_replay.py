#!/usr/bin/env python3
"""One-time, headless conversion of historical decisions into native snapshots."""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
from replay_controls import atomic_json
ROOT=Path(__file__).resolve().parent.parent

def publish_index(source, captured=None):
 source=Path(source).resolve();captured=Path(captured or source).resolve();trace=source/'jev-decisions.jsonl'
 rows=[r for line in trace.read_text().splitlines() if (r:=json.loads(line)).get('kind')=='decision']
 expected=[str(r['decision_id']) for r in rows]
 if not expected or expected!=[str(i+1) for i in range(len(rows))]:raise ValueError('Snapshots require contiguous recorded decision IDs')
 log=[json.loads(l) for l in (captured/'decisions.jsonl').read_text().splitlines()]
 verified={str(r['data']['id']) for r in log if r['kind']=='snapshot_verified'}
 if not set(expected)<=verified:raise RuntimeError(f'Snapshot capture incomplete: {len(set(expected)&verified)}/{len(expected)} verified; inspect {captured}')
 snapshots=captured/'snapshots'
 if any(not (snapshots/(n+'.json.gz')).is_file() for n in expected):raise RuntimeError('Missing snapshot files')
 result=dict(schema=1,mechanism='direct_snapshot',source_run=source.name,directory=str(snapshots),count=len(rows),trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(),conversion_run=captured.name if captured!=source else None,model_calls=0)
 atomic_json(source/'snapshot-index.json',result)
 return result

def prepare(source):
 source=Path(source).resolve();trace=source/'jev-decisions.jsonl'
 rows=[r for line in trace.read_text().splitlines() if (r:=json.loads(line)).get('kind')=='decision']
 manifest=json.loads((source/'manifest.json').read_text());run_id='snapshots-'+source.name+'-'+str(time.time_ns())
 env=os.environ.copy();env['DEALMAKER_SNAPSHOT_CAPTURE']='1'
 subprocess.run([sys.executable,str(ROOT/'scripts/run_jev.py'),'--id',run_id,'--seed',manifest['seed'],'--character',manifest.get('character','dealmaker'),'--headless','--replay',str(trace),'--max-decisions',str(len(rows)),'--timeout','1800'],cwd=ROOT,env=env,check=True)
 result=publish_index(source,ROOT/'docs/playtests/runs'/run_id);print(json.dumps(result),flush=True);return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();prepare(a.run)
