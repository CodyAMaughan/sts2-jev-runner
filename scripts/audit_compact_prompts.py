"""Offline candidate requests: no model calls. Optional tiktoken is only a proxy."""
import argparse,json,os,statistics
from pathlib import Path
from strategy_registry import Strategy
from jev_playtest import make_request

def audit(run,version):
    import tiktoken
    enc=tiktoken.get_encoding('cl100k_base')
    os.environ['DEALMAKER_STRATEGY_VERSION']=version
    strategy=Strategy.load();items=[];examples=[]
    for line in (run/'jev-decisions.jsonl').read_text().splitlines():
        row=json.loads(line)
        if not row.get('request'):continue
        obs=row['observation'];prompt,selection=strategy.prompt(obs,'ironclad')
        candidate=make_request(obs,prompt,'jev-latest','ironclad')
        old=len(enc.encode(json.dumps(row['request'],separators=(',',':'))));new=len(enc.encode(json.dumps(candidate,separators=(',',':'))))
        actual=row['response']['usage']['input_tokens']
        items.append({'decision':row['decision_id'],'kind':obs['kind'],'old_proxy_tokens':old,'new_proxy_tokens':new,'old_provider_tokens':actual,'calibrated_estimate':round(actual*new/old)})
        if obs['kind'] not in {x['kind'] for x in examples}:
            examples.append({'kind':obs['kind'],'decision':row['decision_id'],'selection':selection,'before':row['request'],'after':candidate})
    result={'status':'DRAFT — no model calls; not a quality or billing measurement','version':version,'tokenizer':'cl100k_base, not Jev tokenizer','source_run':run.name,'calls':len(items),'old_provider_average':statistics.mean(x['old_provider_tokens'] for x in items),'old_proxy_average':statistics.mean(x['old_proxy_tokens'] for x in items),'new_proxy_average':statistics.mean(x['new_proxy_tokens'] for x in items),'calibrated_estimate_average':statistics.mean(x['calibrated_estimate'] for x in items),'reduction_fraction':1-sum(x['new_proxy_tokens'] for x in items)/sum(x['old_proxy_tokens'] for x in items),'limits':['New Neow/rest/Skip bridge fields are absent in historical observations.','Provider serialization and tokenization may differ; live measured average remains unverified.','Combat piles keep names/counts rather than all effects.'],'decisions':items}
    return result,examples
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--version',default='1.1.2');p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    result,examples=audit(args.run,args.version);args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'prompt-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    (args.output/'request-examples.json').write_text(json.dumps(examples,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='decisions'},indent=2))
