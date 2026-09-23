"""Offline, room-level evidence and prompt-size analysis. Never calls a model."""
import collections,json,statistics,sys
from pathlib import Path
RATE=.042/1_000_000

def read(path):
 if not path.exists():return []
 out=[]
 for line in path.read_text().splitlines():
  try:out.append(json.loads(line))
  except json.JSONDecodeError:pass
 return out

def state(obs):return obs['state'].get('game',obs['state'])
def size(v):return len(json.dumps(v,separators=(',',':'),ensure_ascii=False))

def review(directory):
 directory=Path(directory);rows=read(directory/'jev-decisions.jsonl');engine=read(directory/'decisions.jsonl')
 result=json.loads((directory/'result.json').read_text()) if (directory/'result.json').exists() else {'outcome':'running'}
 decisions=[r for r in rows if r.get('kind')=='decision'];groups=collections.defaultdict(list)
 for r in decisions:groups[(state(r['observation']).get('act'),state(r['observation']).get('floor'))].append(r)
 ends={(r['data'].get('act'),r['data'].get('floor')):r['data'] for r in engine if r['kind']=='combat_end'}
 rooms=[];components=collections.Counter();flags=[]
 for (act,floor),rs in groups.items():
  fights=[r for r in rs if r['observation']['kind']=='combat'];calls=[r for r in rs if r.get('response')]
  usage=[r['response'].get('usage',{}) for r in calls];tokens=sum(u.get('input_tokens',0) for u in usage)
  first=state((fights or rs)[0]['observation']);last=state((fights or rs)[-1]['observation'])
  item={'act':act,'floor':floor,'room':first.get('room'),'decision_kinds':dict(collections.Counter(r['observation']['kind'] for r in rs)),'decisions':len(rs),'model_calls':len(calls),'input_tokens':tokens,'output_tokens':sum(u.get('output_tokens',0) for u in usage),'estimated_cost_usd':tokens*RATE,'mean_input_tokens':round(tokens/len(calls),1) if calls else 0}
  if fights:
   hp=[state(r['observation'])['player']['hp'] for r in fights];end=ends.get((act,floor));dead=result.get('outcome')=='death' and floor==state(decisions[-1]['observation']).get('floor')
   if dead:hp.append(0)
   item.update(enemies=[e['creature']['name'] for e in first.get('enemies') or []],turns=max(state(r['observation']).get('turn') or 0 for r in fights),starting_hp=hp[0],last_combat_hp=hp[-1],post_combat_hp=end.get('player',{}).get('hp') if end else None,observed_hp_loss=sum(max(0,a-b) for a,b in zip(hp,hp[1:])),combat_complete=bool(end) or dead,death=dead)
   item['assessment']='failed' if dead else 'costly' if item['observed_hp_loss']>=30 else 'clean_candidate' if end and item['observed_hp_loss']<=10 and item['turns']<=5 else 'review'
  rooms.append(item)
  for r in rs:
   payload=r.get('request')
   if payload:
    ps=payload['state'];components['strategy']+=size(ps.get('strategy'));components['rules_and_format']+=size({k:ps[k] for k in ('rules','format','character') if k in ps});components['card_definitions']+=size(ps.get('card_definitions',{}));components['game_state']+=size(ps.get('decision'));components['legal_actions']+=size(payload['questions'])
   o=r['observation'];g=state(o)
   if o['kind']!='combat':continue
   chosen=next(a['option'] for a in o['actions'] if a['id']==r['action_id']);enemies=g.get('enemies') or []
   if len(enemies)==1:
    enemy=enemies[0];lethals=[a for a in o['actions'] if a['option'].get('action')=='play_card' and a['option'].get('enemy_index')==enemy['index'] and (a['option'].get('card',{}).get('preview_damage_per_hit') or 0)>=enemy['creature']['hp']+enemy['creature']['block']]
    if lethals and chosen.get('action')=='end_turn':flags.append({'floor':floor,'decision':r['decision_id'],'type':'ended_with_apparent_lethal','offered':lethals,'caveat':'Inspect self-damage, retaliation and damage modifiers before calling this an error.'})
   if chosen.get('card',{}).get('name')=='Defend' and sum(i.get('total_damage',0) for e in enemies for i in e.get('intents',[]))==0:
    flags.append({'floor':floor,'decision':r['decision_id'],'type':'defend_without_attack_intent','hand':[c['card']['name'] for c in g.get('hand',[])],'caveat':'Block-to-damage, retained Block, statuses, or other on-play effects may justify this.'})
 report={'run':directory.name,'result':result,'rooms':rooms,'total_input_tokens':sum(r['input_tokens'] for r in rooms),'total_output_tokens':sum(r['output_tokens'] for r in rooms),'model_calls':sum(r['model_calls'] for r in rooms),'estimated_cost_usd':sum(r['estimated_cost_usd'] for r in rooms),'pricing':{'input_per_million_usd':.042,'output_per_million_usd':0,'source':'https://typesafe.ai/blog/introducing-system-one-models-and-jev','basis':'Reported API usage times published rate; not an invoice'},'prompt_component_characters':dict(components),'review_flags':flags,'limits':'HP loss sums observed combat HP decreases, including fatal loss, excluding healing. Engine combat-end HP can include Burning Blood. Component sizes are JSON character counts, not tokenizer counts. Clean candidates are not certified solved encounters.'}
 (directory/'room-review.json').write_text(json.dumps(report,indent=2)+'\n')
 return report
if __name__=='__main__':
 r=review(sys.argv[1]);print(json.dumps({k:v for k,v in r.items() if k not in ('review_flags',)},indent=2))
