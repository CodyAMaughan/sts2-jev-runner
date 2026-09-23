"""Paid, action-only counterfactual evaluation. Never submits actions to the game."""
import argparse, json, os, time
from pathlib import Path
from collections import defaultdict
from jev_playtest import request, make_request, fingerprint
from decision_models import JevModel
from playtest_config import typesafe_key
from strategy_registry import Strategy
from decision_memory import DecisionMemory

ROOT=Path(__file__).resolve().parent.parent
# Predeclared behavioral checks, not claims of globally optimal play.
CASES=[('03',12,'inspect'),('03',19,'cheap_kill'),('03',40,'bash_first'),('03',46,'block'),
       ('03',58,'block'),('03',83,'block'),('03',106,'block'),('03',111,'bash_first'),
       ('03',113,'block'),('03',116,'attack'),('03',127,'leave_declined'),
       ('01',33,'fetch_attack'),('02',21,'cheap_kill'),('02',46,'strip_or_block'),
       ('02',13,'take_card'),('02',75,'lethal')]

def accepted(case,option):
    action=option.get('action');card=option.get('card',{});name=card.get('name','').rstrip('+')
    if case=='inspect':return action=='claim_reward' and option.get('type')=='CardReward'
    if case=='leave_declined':return action=='proceed'
    if case=='cheap_kill':return action=='play_card' and name=='Strike' and option.get('enemy_index')==0
    if case=='bash_first':return action=='play_card' and name=='Bash'
    if case=='block':return action=='play_card' and name in {'Defend','True Grit'} or action=='use_potion' and option.get('id')=='SPEED_POTION'
    if case=='attack':return action=='play_card' and name=='Strike'
    if case=='fetch_attack':return action=='select_card' and name=='Strike'
    if case=='strip_or_block':return action=='play_card' and name in {'Strike','Defend'} or action=='use_potion' and option.get('id')=='SPEED_POTION'
    if case=='take_card':return action=='select_card'
    if case=='lethal':return action=='play_card' and name=='Perfected Strike'
    raise ValueError(case)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--repeats',type=int,default=2);ap.add_argument('--candidate-only',action='store_true');args=ap.parse_args()
    os.environ['DEALMAKER_STRATEGY_VERSION']='1.1.3';strategy=Strategy.load();adapter=JevModel(request,typesafe_key())
    cache={};results=[];args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as out:
      for run,number,case in CASES:
        if run not in cache:
          path=ROOT/f'docs/playtests/runs/jev-ironclad-overgrowth-v112-{run}/jev-decisions.jsonl'
          cache[run]=[r for l in path.read_text().splitlines() if (r:=json.loads(l)).get('kind')=='decision']
        rows=cache[run];row=next(r for r in rows if str(r['decision_id'])==str(number));obs=row['observation'];memory=DecisionMemory()
        for prior in rows:
          if prior is row:break
          memory.observe(prior['observation'],prior['action_id'])
        model_obs=memory.enrich(obs);model_obs['context_policy']=strategy.packet['observation_policy']
        prompt,selection=strategy.prompt(model_obs,'ironclad');candidate=make_request(model_obs,prompt,'jev-latest','ironclad','decision-v3')
        expected=[a['id'] for a in obs['actions'] if accepted(case,a['option'])]
        if not expected:raise ValueError(f'No accepted action for {case} {number}')
        variants=[('candidate',candidate)] if args.candidate_only else [('baseline',row['request']),('candidate',candidate)]
        for variant,payload in variants:
          for repeat in range(args.repeats):
            start=time.monotonic();chosen,response,meta=adapter.decide(payload)
            result={'run':run,'decision':number,'case':case,'variant':variant,'repeat':repeat,'state_sha256':fingerprint(obs),'strategy_sha256':strategy.sha256 if variant=='candidate' else row.get('strategy_selection',{}).get('packet_sha256'),'accepted_ids':expected,'chosen':chosen,'passed':chosen in expected,'request':payload,'response':response,'latency_seconds':time.monotonic()-start,**meta}
            out.write(json.dumps(result)+'\n');out.flush();results.append(result)
            print(run,number,case,variant,chosen,'PASS' if result['passed'] else 'FAIL',response.get('usage'),flush=True)
    summary={}
    for variant in {r['variant'] for r in results}:
      rr=[r for r in results if r['variant']==variant];summary[variant]={'passed':sum(r['passed'] for r in rr),'total':len(rr),'input_tokens':sum(r['response'].get('usage',{}).get('input_tokens',0) for r in rr),'cost_usd':sum(r.get('cost_usd') or 0 for r in rr)}
    args.output.with_suffix('.summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
