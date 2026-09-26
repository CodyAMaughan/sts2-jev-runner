#!/usr/bin/env python3
"""Run one isolated, real-engine trial. This never opens the user's normal profile."""
import argparse, hashlib, json, os, shutil, subprocess, time, signal, threading
from pathlib import Path
from playtest_config import display_args
root = Path(__file__).resolve().parent.parent
p=argparse.ArgumentParser()
p.add_argument('--id',required=True);p.add_argument('--seed',required=True)
p.add_argument('--policy',choices=['balanced','boast','wall','favor','status'],required=True)
p.add_argument('--timeout',type=int,default=1650)
display=p.add_mutually_exclusive_group()
display.add_argument('--headed',action='store_true',help='Watch the isolated game in a window')
display.add_argument('--headless',action='store_true',help='Run without a window (default)')
a=p.parse_args()
if not a.id.replace('-','').replace('_','').isalnum():raise SystemExit('invalid run id')
# DEALMAKER_SLOT selects an independent isolated runner clone (own game copy,
# profile, lock) so runs can proceed in parallel; empty = the original slot.
slot=os.environ.get('DEALMAKER_SLOT','')
if slot and not slot.isdigit():raise SystemExit('invalid DEALMAKER_SLOT')
base=root/'.tooling'/('overnight'+slot)
profile='DealmakerPlaytests-20260918'+('-'+slot if slot else '')
runner=base/'Runner.app/Contents/MacOS'
userdata=base/'userdata'
logical=Path('/Users/cmaughan/Library/Application Support')/profile
if not logical.is_symlink() or logical.resolve()!=userdata:raise SystemExit('save isolation link mismatch')
if f'config/custom_user_dir_name="{profile}"' not in (runner/'override.cfg').read_text():raise SystemExit('save isolation config mismatch')
lock=base/'run.lock'
try: fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
except FileExistsError:raise SystemExit('Another run owns isolated profile; inspect run.lock before proceeding')
os.write(fd,str(os.getpid()).encode());os.close(fd)
artifact=root/'docs/playtests/runs'/a.id
if artifact.exists():lock.unlink();raise SystemExit('run ID already exists; never overwrite evidence')
artifact.mkdir(parents=True)
normal=Path('/Users/cmaughan/Library/Application Support/SlayTheSpire2/steam/76561198027063952/modded/profile1/saves/current_run.save')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
original_hash=sha(normal)
recorder=None;record_log=None
recording=os.environ.get("DEALMAKER_RECORD")=="1"
if recording and not a.headed:raise SystemExit("Recording requires headed mode")
replay_source=os.environ.get('DEALMAKER_REPLAY_SOURCE')
mod_stash=artifact/'temporarily-excluded-mods'
try:
    if replay_source:
        from replay_environment import isolate_mods
        isolate_mods(runner/'mods',replay_source,mod_stash)
    if userdata.exists():
        archive=base/'previous-userdata'/str(time.time_ns())
        archive.parent.mkdir(parents=True,exist_ok=True);shutil.move(userdata,archive)
    settings=userdata/'default/1/settings.save';settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({'schema_version':5,'seen_ea_disclaimer':True,'mod_settings':{'mods_enabled':True,'mod_list':[]}}))
    expected={name:sha(root/name) for name in ['cards.json','card-tuning.json','bin/Release/net9.0/Dealmaker.dll','tests/overnight/bin/Release/net9.0/OvernightHarness.dll']}
    # Deploy only to the disposable clone.
    for name in ['Dealmaker.dll','Dealmaker.json']:
        shutil.copy2(root/'dist/Dealmaker'/name,runner/'mods/Dealmaker'/name)
    for folder in ('art','character','icons'):
        shutil.copytree(root/'dist/Dealmaker'/folder,runner/'mods/Dealmaker'/folder,dirs_exist_ok=True)
    for name,source in [('OvernightHarness.dll',Path(replay_source)/'build/OvernightHarness.dll' if replay_source and os.environ.get('DEALMAKER_SNAPSHOT_CAPTURE')!='1' and not os.environ.get('DEALMAKER_SNAPSHOT_PLAYBACK') and not os.environ.get('DEALMAKER_SNAPSHOT_RESUME') else root/'tests/overnight/bin/Release/net9.0/OvernightHarness.dll'),('OvernightHarness.json',root/'tests/overnight/OvernightHarness.json')]:
        shutil.copy2(source,runner/'mods/OvernightHarness'/name)
    metadata={'character':os.environ.get('DEALMAKER_CHARACTER','dealmaker'),'display_mode':'headed' if a.headed else 'headless','id':a.id,'seed':a.seed,'policy':a.policy,'mode':'actual_game_engine_remote_controller' if os.environ.get('DEALMAKER_REMOTE')=='1' else 'actual_game_engine_paid_heuristic_agent','remote_strategy':os.environ.get('DEALMAKER_REMOTE_STRATEGY'), 'balance_version':json.loads((root/'dist/Dealmaker/Dealmaker.json').read_text())['version'],'build_version':json.loads((root/'dist/Dealmaker/Dealmaker.json').read_text())['version'],'hashes':expected,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'recording_requested':recording,'recording_audio':False,'steam':False,'save_isolation':str(logical),'original_save_sha256':original_hash}
    (artifact/'manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (artifact/'build').mkdir()
    shutil.copy2(runner/'mods/Dealmaker/Dealmaker.dll',artifact/'build/Dealmaker.dll')
    shutil.copy2(runner/'mods/OvernightHarness/OvernightHarness.dll',artifact/'build/OvernightHarness.dll')
    env=os.environ.copy();env.update(DEALMAKER_HEADED="1" if a.headed else "0",DEALMAKER_TEST_USERDIR=str(logical),DEALMAKER_TEST_LOG=str(artifact/'decisions.jsonl'),DEALMAKER_POLICY=a.policy)
    command=[str(runner/'Slay the Spire 2'),*display_args(a.headed),'--force-steam=off','--autoslay','--seed='+a.seed,'--log-file',str(artifact/'game.log')]
    print('START '+a.id+' '+a.policy+' seed='+a.seed,flush=True)
    start=time.monotonic();timed_out=False
    with (artifact/'stdout.log').open('w') as output:
        process=subprocess.Popen(command,cwd=root,env=env,stdout=output,stderr=subprocess.STDOUT)
        if recording:
            record_log=(artifact/'recording.log').open('w')
            recorder=subprocess.Popen([str(root/'.tooling/record-game'),str(process.pid),str(artifact/'game.mp4'),str(artifact/'recording.stop')],stdout=record_log,stderr=subprocess.STDOUT)
        def stop_child(*_):
            process.terminate()
            timer=threading.Timer(5,lambda: process.kill() if process.poll() is None else None)
            timer.daemon=True;timer.start()
        signal.signal(signal.SIGTERM, stop_child)
        try:
            deadline=time.monotonic()+a.timeout
            while process.poll() is None:
                if recorder is not None and recorder.poll() is not None:
                    process.terminate()
                    raise RuntimeError('Recorder stopped while game was active; refusing an unrecorded run')
                if time.monotonic()>deadline:raise subprocess.TimeoutExpired(command,a.timeout)
                time.sleep(.2)
            code=process.returncode
        except subprocess.TimeoutExpired:
            timed_out=True;process.terminate()
            try:code=process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();code=process.wait()
    if recorder is not None:
        (artifact/'recording.stop').touch()
        recording_code=recorder.wait(timeout=20)
        from recording_validation import validate
        (artifact/'recording.json').write_text(json.dumps(validate(artifact,recording_code),indent=2)+'\n')
    rows=[]
    log=artifact/'decisions.jsonl'
    if log.exists():
        for line in log.read_text().splitlines():
            try:rows.append(json.loads(line))
            except json.JSONDecodeError:pass
    ends=[r['data'] for r in rows if r.get('kind')=='run_end']
    outcome=ends[-1]['outcome'] if ends else 'snapshot_verified' if any(r.get('kind')=='snapshot_navigation_verified' for r in rows) else 'replay_stopped' if any(r.get('kind')=='snapshot_playback_stopped' for r in rows) else 'controller_stopped' if any(r.get('kind')=='controller_stop' for r in rows) else 'timeout' if timed_out else 'incomplete_or_infrastructure_failure'
    result={'outcome':outcome,'process_exit':code,'elapsed_seconds':round(time.monotonic()-start,2),'completed_run':outcome in ('death','victory'),'original_save_unchanged':sha(normal)==original_hash}
    (artifact/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    if userdata.exists():shutil.move(userdata,artifact/'saves');userdata.mkdir()
    print('END '+a.id+' '+json.dumps(result),flush=True)
    if not result['original_save_unchanged']:raise SystemExit('STOP: original save changed unexpectedly')
finally:
    if "process" in locals() and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    if recorder is not None and recorder.poll() is None:
        (artifact/'recording.stop').touch()
        try:recorder.wait(timeout=20)
        except subprocess.TimeoutExpired:recorder.terminate();recorder.wait(timeout=5)
    if record_log:record_log.close()
    if replay_source:
        from replay_environment import restore_mods
        restore_mods(runner/'mods',mod_stash)
    lock.unlink(missing_ok=True)
