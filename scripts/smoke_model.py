#!/usr/bin/env python3
"""One recorded decision, no game process or submitted game action."""
import argparse,json,time,sys,urllib.error,subprocess
from pathlib import Path
from decision_models import BifrostModel,CliModel,InvalidDecision
from jev_playtest import request,make_request
from strategy_registry import Strategy
ROOT=Path(__file__).resolve().parent.parent
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--backend',choices=['bifrost','codex','claude'],required=True);p.add_argument('--model',required=True);a=p.parse_args()
    row=next(json.loads(l) for l in (ROOT/'docs/playtests/runs/jev-donaldtrump-headed-01/jev-decisions.jsonl').read_text().splitlines() if json.loads(l).get('decision_id')=='2')
    strategy=Strategy.load();prompt,selection=strategy.prompt(row['observation']);payload=make_request(row['observation'],prompt,a.model)
    adapter=BifrostModel(request,'http://127.0.0.1:18767/v1') if a.backend=='bifrost' else CliModel(a.backend)
    result={'kind':'model_smoke','backend':a.backend,'requested_model':a.model,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'source_run':'jev-donaldtrump-headed-01','source_decision':'2','game_actions_submitted':0,'strategy_selection':selection,'request':payload}
    start=time.monotonic()
    try:
        chosen,response,meta=adapter.decide(payload);result.update(status='passed',action_id=chosen,response=response,**meta)
    except Exception as error:
        result.update(status='failed',error_type=type(error).__name__)
        if isinstance(error,urllib.error.HTTPError):
            result['http_status']=error.code
            # Error responses should not contain credentials; retain only public error message fields.
            try:
                body=json.loads(error.read());message=body.get('error',{});result['error_message']=str(message.get('message',''))[:1000] if isinstance(message,dict) else 'Gateway returned an error'
            except Exception:pass
        elif isinstance(error,subprocess.CalledProcessError):
            result['exit_code']=error.returncode
            # Output from our CLI-only invocation, which receives no gateway/provider keys.
            result['error_message']=(error.stderr or error.stdout or '')[-1800:]
        elif isinstance(error,InvalidDecision):result['attempts']=error.attempts
        else:result['error_message']=str(error)[:500]
    result['elapsed_seconds']=round(time.monotonic()-start,3)
    out=ROOT/'docs/playtests/model-smokes';out.mkdir(parents=True,exist_ok=True)
    path=out/(a.backend+'-'+a.model.replace('/','_')+'-'+str(time.time_ns())+'.json');path.write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k in ('backend','requested_model','status','action_id','elapsed_seconds','error_type','http_status','exit_code','error_message')},indent=2))
    print('Report:',path)
    sys.exit(0 if result['status']=='passed' else 1)
