"""Offline compression experiment only. Not imported by the game runner."""
import json,sys
from pathlib import Path
from decision_prompts import project,clean

def preview(row):
 original=row['request'];obs=row['observation'];definitions={};refs={}
 def compress(v):
  if isinstance(v,list):return [compress(x) for x in v]
  if not isinstance(v,dict):return v
  if {'id','name','type','text','cost'}<=v.keys():
   c={k:v[k] for k in ('name','type','cost','text','keywords') if k in v}
   # Keep variables if the card text contains unresolved format placeholders.
   if '{' in c.get('text',''):c['variables']=v.get('variables')
   c=clean(c);key=json.dumps(c,sort_keys=True)
   if key not in refs:
    ref='c'+str(len(refs));refs[key]=ref;definitions[ref]=c
   return {'card':refs[key]}
  return {k:compress(x) for k,x in clean(v).items()}
 decision=compress(project(obs));actions={}
 for a in obs['actions']:
  option=dict(a['option']);card=option.get('card') or {};damage=card.get('preview_damage_per_hit')
  if option.get('enemy_index',-1)>=0:option.pop('target',None)
  option=compress(option)
  if damage is not None:option['damage_per_hit']=damage
  actions[a['id']]=option
 return {'state':{'rules':original['state']['rules'],'strategy':original['state']['strategy'],'character':original['state']['character'],'format':'card references cards; unordered piles use counts; enemy_index indexes enemies; omitted collections empty.','cards':definitions,'decision':decision},'questions':{'action':{'type':'choice','instructions':original['questions']['action']['instructions'],'criteria':{k:json.dumps(v,separators=(',',':')) for k,v in actions.items()}}},'model':original['model']}

if __name__=='__main__':
 p=Path(sys.argv[1]);rows=[json.loads(l) for l in p.read_text().splitlines()];out=[]
 for r in rows:
  if r.get('kind')!='decision' or not r.get('request'):continue
  proposed=preview(r);old=len(json.dumps(r['request'],separators=(',',':')));new=len(json.dumps(proposed,separators=(',',':')))
  out.append({'decision':r['decision_id'],'kind':r['observation']['kind'],'old_json_characters':old,'proposed_json_characters':new,'reduction_pct':round(100*(1-new/old),1),'reported_original_input_tokens':r['response']['usage']['input_tokens']})
 artifact={'status':'OFFLINE PROPOSAL — NOT APPROVED OR EXECUTED','changes':['Remove internal card IDs and numeric variables already rendered in text.','Share card definitions across hand/piles/targets, placing target-specific damage on the action.','Preserve card effect text, costs, keywords, current state, all legal actions and the existing strategy.'], 'limits':'JSON character savings are not measured token or billing savings. Jev accuracy with this format has not been tested. Unresolved card text retains variables.','decisions':out}
 dest=p.parent/'compact-preview-audit.json';dest.write_text(json.dumps(artifact,indent=2)+'\n')
 for r in rows:
  if r.get('request') and r['observation']['kind']=='combat':
   (p.parent/'compact-request-example.json').write_text(json.dumps({'status':artifact['status'],'decision':r['decision_id'],'before':r['request'],'after':preview(r)},indent=2)+'\n');break
 print(json.dumps({'moves':len(out),'original_characters':sum(r['old_json_characters'] for r in out),'proposed_characters':sum(r['proposed_json_characters'] for r in out)},indent=2))

# A second, explicitly lossy hypothesis for selected simple fights only.
# This remains offline and is deliberately not reachable from the live runner.
def simple_fight_preview(row):
 obs=row['observation'];g=obs['state'].get('game',obs['state'])
 if obs['kind']!='combat' or g.get('room')!='Monster':raise ValueError('Normal combat only')
 def card(c):return clean({'name':c['name'],'cost':c['cost'],'effect':c['text'],'keywords':c.get('keywords')})
 def creature(c):return clean({k:c[k] for k in ('name','hp','block','powers') if k in c})
 hand={str(h['index']):card(h['card']) for h in g['hand']}
 choices={}
 for a in obs['actions']:
  op=a['option'];c=op.get('card',{});kind=op.get('action')
  if kind=='play_card':
   target=op.get('enemy_index',-1)
   choices[a['id']]=f"Play hand {op['hand_index']} ({c.get('name')}, cost {c.get('cost')})"+(f" on enemy {target}" if target>=0 else '')+(f"; damage per hit {c['preview_damage_per_hit']}" if c.get('preview_damage_per_hit') is not None else '')
  else:choices[a['id']]=json.dumps(clean(op),separators=(',',':'))
 state={'rules':'Choose an offered action. Energy is spent per card. Block absorbs damage and expires next turn. Killing the last enemy prevents its attack. Card text and legal options override advice.',
        'advice':'Check lethal first. Use temporary Strength before attacks; build Block before Body Slam. Do not spend energy on Block against zero incoming damage without a specific payoff.',
        'you':creature(g['player']),'energy':g['energy'],'hand':hand,'enemies':{str(e['index']):{'creature':creature(e['creature']),'intents':e['intents']} for e in g['enemies']},'relics':g.get('relics',[]),'potions':g.get('potions',[]),
        'piles':{k:len(g.get(k) or []) for k in ('draw_pile_unordered','discard','exhaust')}}
 return {'model':row['request']['model'],'state':clean(state),'questions':{'action':{'type':'choice','instructions':'Choose the most useful action now.','criteria':choices}}}
