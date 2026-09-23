"""Bounded real-engine transport test. No Typesafe API use."""
import os,secrets,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];os.chdir(root)
run_id=sys.argv[1];env=os.environ.copy();env.update(DEALMAKER_REMOTE='1',DEALMAKER_BRIDGE_TOKEN=secrets.token_hex(24))
log=root/'docs/playtests'/f'{run_id}-controller.log'
with log.open('x') as out:
 game=subprocess.Popen(['python3','scripts/run_playtest.py','--id',run_id,'--seed','JEVBRIDGETEST','--policy','balanced','--timeout','100'],env=env,stdout=out,stderr=subprocess.STDOUT)
 pilot=subprocess.Popen(['python3','scripts/jev_playtest.py','--mock','--log',f'docs/playtests/{run_id}.jsonl','--max-decisions','150','--max-seconds','90'],env=env,stdout=out,stderr=subprocess.STDOUT)
 game.wait();pilot.terminate();pilot.wait()
print(log.read_text()[-3500:])
