#!/usr/bin/env python3
"""Launch one isolated game and a Jev (or explicit mock) controller."""
import argparse, os, secrets, signal, subprocess, sys, time
from pathlib import Path
from jev_playtest import request
from summarize_jev import summarize
from playtest_config import typesafe_key

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--act1-overgrowth',action='store_true')
    p.add_argument('--record',action='store_true',help='Record only the headed game window to MP4 (no audio)')
    p.add_argument('--strategy-version',default='1.1.0')
    p.add_argument('--id',required=True);p.add_argument('--seed',required=True)
    p.add_argument('--character',default='dealmaker',choices=['dealmaker','ironclad','silent','regent','necrobinder','defect','harry'])
    p.add_argument('--strategy',default='balanced',choices=['balanced','boast','wall','favor','bargain'])
    p.add_argument('--backend',choices=['jev','bifrost','codex','claude'],default='jev')
    p.add_argument('--strategy-file',type=Path);p.add_argument('--model')
    p.add_argument('--max-decisions',type=int,default=1000);p.add_argument('--timeout',type=int,default=3600)
    p.add_argument('--port',type=int,default=18765);p.add_argument('--mock',action='store_true');p.add_argument('--replay',type=Path)
    p.add_argument('--replay-controls',type=Path);p.add_argument('--seek-index',type=int,default=0)
    p.add_argument('--snapshot-resume',type=Path,help='Inject this captured <n>.json.gz snapshot into the fresh '
                    'game instead of starting normally, landing it exactly at --seek-index instantly instead of '
                    'replaying every earlier decision to get there. Requires --replay (the actions from '
                    '--seek-index onward are still replayed normally, with real animation, from that point).')
    p.add_argument('--no-snapshots',action='store_true',help='Disable native decision snapshots for this run')
    display=p.add_mutually_exclusive_group()
    display.add_argument('--headed',action='store_true',help='Watch play in a 1280×720 game window')
    display.add_argument('--headless',action='store_true',help='Run without a window (default)')
    p.add_argument('--decision-delay',type=float,default=None,help='Seconds before each action: default 1 in headed mode, 0 headless')
    a=p.parse_args();root=Path(__file__).resolve().parent.parent
    if a.record and not a.headed:p.error('--record requires --headed')
    if not a.model:
        if a.backend!='jev':p.error('Specify --model for this backend')
        a.model='jev-latest'
    if not a.id.replace('-','').replace('_','').isalnum():p.error('Invalid run id')
    if not a.mock and not a.replay:
        from strategy_registry import require_approved
        require_approved(a.strategy_version)
        if a.strategy_file or a.strategy!='balanced':p.error('A changed strategy requires a reviewed, approved version before running')
    delay=a.decision_delay if a.decision_delay is not None else (1.0 if a.headed else 0.0)
    if not 0 <= delay <= 60:p.error('--decision-delay must be between 0 and 60 seconds')
    if not a.mock and not a.replay and a.backend=='jev' and not typesafe_key():p.error('Set TYPESAFE_API_KEY in .env.local or your environment before starting a live run')
    if a.mock and a.replay:p.error('Choose mock or replay, not both')
    if a.snapshot_resume and not a.replay:p.error('--snapshot-resume requires --replay')
    artifact=root/'docs/playtests/runs'/a.id
    if artifact.exists():p.error('Run ID already exists; choose a new ID')
    env=os.environ.copy();env.update(DEALMAKER_REMOTE='1',DEALMAKER_REMOTE_STRATEGY=a.strategy,DEALMAKER_BRIDGE_PORT=str(a.port),DEALMAKER_BRIDGE_TOKEN=secrets.token_hex(24))
    env['DEALMAKER_STRATEGY_VERSION']=a.strategy_version
    if not a.replay and not a.no_snapshots:env['DEALMAKER_SNAPSHOT_CAPTURE']='1'
    if a.record:env['DEALMAKER_RECORD']='1'
    env.pop('DEALMAKER_QUOTE_SMOKE',None)
    if a.act1_overgrowth:env['DEALMAKER_ACT1_OVERGROWTH']='1'
    env['DEALMAKER_CHARACTER']=a.character
    from strategy_registry import version_packet
    env.pop('DEALMAKER_RULES_V2',None)
    env.pop('DEALMAKER_PLANNING_CONTEXT',None)
    if a.replay:
        env['DEALMAKER_REPLAY_SOURCE']=str(a.replay.resolve().parent)
        import json
        with a.replay.open() as evidence:
            header=next((row for line in evidence if (row:=json.loads(line)).get('kind')=='controller'),{})
        with a.replay.open() as evidence:
            first=next((row['observation'] for line in evidence if (row:=json.loads(line)).get('kind')=='decision'),{})
        first_state=first.get('state',{});first_game=first_state.get('game',first_state)
        if first_game.get('act_id')=='OVERGROWTH':env['DEALMAKER_ACT1_OVERGROWTH']='1'
        if header.get('planning_context'):env['DEALMAKER_PLANNING_CONTEXT']='1'
        if header.get('prompt_version')=='decision-v3':env['DEALMAKER_RULES_V2']='1'
    elif version_packet(a.strategy_version).get('prompt_format')=='decision-v3':env['DEALMAKER_RULES_V2']='1'
    if not a.replay and version_packet(a.strategy_version).get('planning_context'):env['DEALMAKER_PLANNING_CONTEXT']='1'
    if a.replay_controls:env['DEALMAKER_REPLAY_CONTROLS']=str(a.replay_controls.resolve())
    if a.snapshot_resume:env['DEALMAKER_SNAPSHOT_RESUME']=str(a.snapshot_resume.resolve())
    game_env=env.copy()
    for key in ('TYPESAFE_API_KEY','BIFROST_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','CODEX_API_KEY'):game_env.pop(key,None)
    game=subprocess.Popen([sys.executable,str(root/'scripts/run_playtest.py'),'--id',a.id,'--seed',a.seed,'--policy','balanced','--timeout',str(a.timeout),'--headed' if a.headed else '--headless'],cwd=root,env=game_env)
    pilot=None
    try:
        # Only the launcher creates the run directory, after acquiring the profile lock.
        deadline=time.monotonic()+15
        while not (artifact/'manifest.json').is_file():
            if game.poll() is not None:raise RuntimeError('Game launcher failed')
            if time.monotonic()>deadline:raise TimeoutError('Game launcher did not initialize')
            time.sleep(.1)
        if a.record:
            deadline=time.monotonic()+40
            while not (artifact/'game.mp4.ready').exists():
                if game.poll() is not None:raise RuntimeError('Recording setup failed; no model calls made')
                if time.monotonic()>deadline:raise TimeoutError('Recording did not become ready; no model calls made')
                time.sleep(.1)
        args=[sys.executable,str(root/'scripts/jev_playtest.py'),'--port',str(a.port),'--strategy',a.strategy,'--model',a.model,'--log',str(artifact/'jev-decisions.jsonl'),'--max-decisions',str(a.max_decisions),'--max-seconds',str(a.timeout),'--decision-delay',str(delay)]
        if a.mock:args.append('--mock')
        if a.replay:args+=['--replay',str(a.replay.resolve())]
        if a.replay_controls:args+=['--replay-controls',str(a.replay_controls.resolve()),'--seek-index',str(a.seek_index)]
        if a.snapshot_resume:args+=['--replay-start-index',str(a.seek_index)]
        if a.strategy_file:args+=['--strategy-file',str(a.strategy_file.resolve())]
        args+=['--character',a.character,'--backend',a.backend]
        with (artifact/'controller.log').open('x') as output:
            pilot=subprocess.Popen(args,cwd=root,env=env,stdout=output,stderr=subprocess.STDOUT)
            while pilot.poll() is None and game.poll() is None:time.sleep(.2)
            if pilot.poll() is not None and game.poll() is None:
                try:request(f'http://127.0.0.1:{a.port}/stop',env['DEALMAKER_BRIDGE_TOKEN'],{},timeout=3)
                except Exception:pass
                try:game.wait(timeout=15)
                except subprocess.TimeoutExpired:game.terminate()
            if pilot.poll() is None:pilot.terminate()
            pilot.wait(timeout=10);game.wait(timeout=15)
        import json
        evidence=[json.loads(line) for line in (artifact/'jev-decisions.jsonl').read_text().splitlines()]
        if any(row.get('kind')=='scope_complete' for row in evidence):
            result_path=artifact/'result.json';result=json.loads(result_path.read_text());result.update(outcome='act1_victory',completed_run=False,completed_scope='overgrowth_act1');result_path.write_text(json.dumps(result,indent=2)+'\n')
        summarize(artifact)
        if game.returncode:raise RuntimeError('Game launcher reported a failed run/check; inspect '+str(artifact/'result.json'))
        if env.get('DEALMAKER_SNAPSHOT_CAPTURE')=='1':
            from prepare_snapshot_replay import publish_index
            publish_index(artifact)
        print('Run artifacts:',artifact)
        print((artifact/'result.json').read_text() if (artifact/'result.json').exists() else 'Run ended before a result was written')
    finally:
        if pilot is not None and pilot.poll() is None:pilot.terminate();pilot.wait(timeout=10)
        if game.poll() is None:game.terminate();game.wait(timeout=15)
if __name__=='__main__':main()
