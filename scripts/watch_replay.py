#!/usr/bin/env python3
"""Load recorded native decision snapshots directly; headless unless requested."""
import argparse,hashlib,json,os,secrets,subprocess,sys,time
from pathlib import Path
from replay_controls import atomic_json
ROOT=Path(__file__).resolve().parent.parent

def snapshot_index(source):
 source=Path(source)
 path=source/'snapshot-index.json'
 if not path.exists():
  from prepare_snapshot_replay import prepare
  return prepare(source)
 data=json.loads(path.read_text())
 if data.get('mechanism')!='direct_snapshot' or data.get('trace_sha256')!=hashlib.sha256((source/'jev-decisions.jsonl').read_bytes()).hexdigest():raise ValueError('Snapshot index does not match recorded decisions')
 directory=Path(data['directory']).resolve()
 if not directory.is_relative_to((ROOT/'docs/playtests/runs').resolve()):raise ValueError('Snapshot directory outside run artifacts')
 if any(not (directory/f'{i+1}.json.gz').is_file() for i in range(data['count'])):raise ValueError('Snapshot index contains missing decisions')
 return data

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--at',type=int,default=1)
 display=p.add_mutually_exclusive_group();display.add_argument('--headed',action='store_true');display.add_argument('--headless',action='store_true')
 p.add_argument('--verify',action='store_true',help='Verify non-sequential native snapshot loads and exit')
 args=p.parse_args();source=args.run.resolve();manifest=json.loads((source/'manifest.json').read_text())
 if hashlib.sha256((source/'build/Dealmaker.dll').read_bytes()).digest()!=hashlib.sha256((ROOT/'dist/Dealmaker/Dealmaker.dll').read_bytes()).digest():p.error('Recorded mod differs from test build; matching mod is required')
 index=snapshot_index(source)
 if not 1<=args.at<=index['count']:p.error('Decision outside recorded run')
 session=ROOT/'docs/playtests/replays'/(source.name+'-snapshot-'+str(time.time_ns()));session.mkdir(parents=True)
 atomic_json(session/'session.json',dict(source=str(source),mechanism='direct_snapshot',images_or_video=False))
 atomic_json(session/'status.json',dict(index=args.at-1,total=index['count'],mode='Loading',seconds=1,mechanism='direct_snapshot'))
 env=os.environ.copy();env.update(DEALMAKER_REPLAY_SOURCE=str(source),DEALMAKER_SNAPSHOT_PLAYBACK=index['directory'],DEALMAKER_REPLAY_CONTROLS=str(session),DEALMAKER_SNAPSHOT_INDEX=str(args.at-1),DEALMAKER_CHARACTER=manifest.get('character','dealmaker'),DEALMAKER_REMOTE='1',DEALMAKER_BRIDGE_TOKEN=secrets.token_hex(24))
 if args.verify:
  env['DEALMAKER_SNAPSHOT_VERIFY']='1'
  env['DEALMAKER_SNAPSHOT_VALIDATE_SCENES']='1'
 else:env.pop('DEALMAKER_SNAPSHOT_VERIFY',None)
 env.pop('DEALMAKER_SNAPSHOT_CAPTURE',None)
 for key in ('TYPESAFE_API_KEY','BIFROST_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY'):env.pop(key,None)
 run_id='replay-'+session.name
 print('Direct snapshot replay:',session,flush=True)
 try:
  subprocess.run([sys.executable,str(ROOT/'scripts/run_playtest.py'),'--id',run_id,'--seed',manifest['seed'],'--policy','balanced','--headed' if args.headed else '--headless','--timeout','14400'],cwd=ROOT,env=env,check=True)
  status=json.loads((session/'status.json').read_text())
  if status.get('mode') not in ('Stopped','Finished','Failed'):
   status.update(mode='Failed',error='Snapshot process ended unexpectedly');atomic_json(session/'status.json',status)
  if status.get('mode')=='Failed':raise RuntimeError('Snapshot replay failed; inspect '+str(ROOT/'docs/playtests/runs'/run_id))
 except Exception as error:
  status=json.loads((session/'status.json').read_text());status.update(mode='Failed',error=str(error));atomic_json(session/'status.json',status);raise
if __name__=='__main__':main()
