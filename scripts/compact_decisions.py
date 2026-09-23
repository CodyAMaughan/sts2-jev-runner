"""Decision-v3. Stateless compact observations; raw trace/actions remain untouched."""
import json,re
from collections import Counter
from decision_prompts import clean, project

VERSION='decision-v3'

def label(value):
    return str(value).removesuffix('_POWER').replace('_',' ').title()

def readable(value):
    if isinstance(value,str):
        return re.sub(r'\[img\]([^[]+)\[/img\]',lambda m:'1 Energy' if 'energy_icon' in m[1] else 'icon '+m[1].split('/')[-1].split('.')[0],value)
    if isinstance(value,list):return [readable(v) for v in value]
    if isinstance(value,dict):return {k:readable(v) for k,v in value.items()}
    return value

def build(obs, strategy, character, rules):
    projected=project(obs)
    game=projected['state']
    combat=obs['kind']=='combat' or (obs['kind'] in {'card_selection','simple_select'} and 'enemies' in game)
    definitions={}; refs={}
    def card(c):
        # Target-specific effects stay separate when text differs. Never merge by name alone.
        d=clean({k:c[k] for k in ('name','cost','type','text','keywords') if k in c})
        if '{' in d.get('text',''):d['variables']=c.get('variables',{})
        key=json.dumps(d,sort_keys=True)
        if key not in refs:
            ref='c'+str(len(refs));refs[key]=ref;definitions[ref]=d
        return refs[key]
    def compact(v):
        if isinstance(v,list):return [compact(x) for x in v]
        if not isinstance(v,dict):return v
        if {'name','type','text','cost'}<=v.keys():return {'card':card(v)}
        return {k:compact(x) for k,x in clean(v).items()}
    if combat:
        for pile in ('draw_pile_unordered','discard','exhaust'):
            if pile in game:
                counts=Counter()
                for entry in game[pile]:counts[entry['card']['name']]+=entry['count']
                game[pile]=dict(counts)
        # These resources belong to the mod, not base Ironclad.
        if character=='ironclad':
            for k in ('boast','boast_attacks','stars','orb_slots','orbs_in_order','osty'):game.pop(k,None)
        # Hand index remains the exact engine index, including duplicates.
        game['hand']={str(h['index']):card(h['card']) for h in game.get('hand',[])}
    actions={}
    for a in obs['actions']:
        op=clean(dict(a['option'])); kind=op.get('action')
        if kind=='play_card':
            c=op.get('card',{});target=op.get('enemy_index',-1)
            # Card definitions preserve modified costs and full current effect text.
            value={'play':op['hand_index'],'card':card(c)}
            if target>=0:value['enemy']=target
            damage=c.get('preview_damage_per_hit')
            if damage is not None:value['damage_before_hp_caps']=damage
            actions[a['id']]='h'+str(value['play'])+((' '+value['card']) if game.get('hand',{}).get(str(value['play']))!=value['card'] else '')+((' -> e'+str(target)) if target>=0 else '')+(('; hit '+str(damage)) if damage is not None else '')
            if obs.get('context_policy') == 'observed-history-v1':
                enemy=next((e for e in game.get('enemies',[]) if e['index']==target),None)
                target_text=''
                if enemy:
                    creature=enemy['creature']
                    target_text=f" Target e{target}: HP {creature['hp']}, Block {creature.get('block',0)}; current hit {damage} before caps."
                actions[a['id']]=f"Play {c.get('name')} (hand {op['hand_index']}, cost {c.get('cost')}): {c.get('text','')}"+target_text
        elif kind in {'use_potion','discard_potion'}:
            value={'action':kind,'slot':op['slot'],'effect':op.get('text'),'potion':op.get('id')}
            if op.get('enemy_index',-1)>=0:value['enemy']=op['enemy_index']
            elif op.get('target'):value['target']='self'
            actions[a['id']]=kind+' slot '+str(op['slot'])+' '+label(op.get('id'))+((' on enemy '+str(op['enemy_index'])) if op.get('enemy_index',-1)>=0 else '')
        elif kind=='end_turn':actions[a['id']]='end turn'
        else:
            if obs.get('context_policy') == 'observed-history-v1':
                if kind=='claim_reward' and op.get('type')=='CardReward':
                    op['text']='Inspect free card offers; adds no card yet. You may Skip after inspection.'
                if kind=='proceed' and obs['kind']=='rewards':
                    op['text']='Leave remaining rewards.'
            actions[a['id']]=compact(op)
            if obs.get('context_policy') == 'observed-history-v1' and kind=='claim_reward' and op.get('type')=='CardReward' and obs.get('observed_history'):
                actions[a['id']]['history']='Card offers were already inspected and declined here. Reopening is not a reroll.'
    context=compact(game)
    if combat:
        # Compact text avoids repeating JSON scaffolding; values and power rules remain.
        def creature(c):
            base=f"HP {c.get('hp')}/{c.get('max_hp','?')} Block {c.get('block',0)}"
            powers=['%s %s: %s'%(label(p.get('id')),p.get('amount'),p.get('text','')) for p in c.get('powers',[])]
            return base+(' | '+'; '.join(powers) if powers else '')
        lines=[f"You: {creature(game.get('player',{}))}",f"Energy {game.get('energy')} Turn {game.get('turn')}",
               'Hand '+', '.join(f'h{i}={ref}' for i,ref in game.get('hand',{}).items())]
        if obs.get('context_policy') == 'observed-history-v1':
            incoming=sum(i.get('total_damage',0) for e in game.get('enemies',[]) for i in e.get('intents',[]))
            lines.insert(0,f"TOTAL enemy attack damage this turn: {incoming}. Current Block: {game.get('player',{}).get('block',0)}.")
        for e in game.get('enemies',[]):
            c=e['creature'];intents='; '.join(' '.join(f'{k}={v}' for k,v in i.items()) for i in e.get('intents',[]))
            lines.append(f"e{e['index']} {c['name']}: {creature(c)} | {intents}")
        for pile in ('draw_pile_unordered','discard','exhaust'):
            if game.get(pile):lines.append(pile+': '+', '.join(f'{name} x{n}' for name,n in game[pile].items()))
        if game.get('relics'):lines.append('Relics: '+'; '.join(f"{label(r['id'])}: {r.get('text','')}" for r in game['relics']))
        if game.get('potions'):lines.append('Potions: '+'; '.join(f"{label(p.get('id'))}: {p.get('text','')}" for p in game['potions'] if p))
        # Preserve less common resources and selection constraints without guessing meanings.
        other={k:v for k,v in context.items() if k not in {'player','energy','turn','hand','enemies','draw_pile_unordered','discard','exhaust','relics','potions'}}
        if other:lines.append(json.dumps(other,separators=(',',':')))
        context='\n'.join(lines)
    # Effects once per distinct card; no repeated JSON field names in each definition.
    definitions={ref:f"{d['name']} | {d['cost']} energy | {d['type']} | {d.get('text','')}"+((' | '+','.join(d['keywords'])) if d.get('keywords') else '')+((' | variables '+json.dumps(d['variables'])) if d.get('variables') else '') for ref,d in definitions.items()}
    result={'rules':'Hidden draws/RNG unknown.' if character=='ironclad' else rules,'strategy':strategy,'format':VERSION+'; h=hand,e=enemy; hit=damage before HP caps; piles unordered; absent lists empty.',
            'cards':definitions,'kind':obs['kind'],'state':context}
    if obs.get('run_plan'):result['run_plan']=obs['run_plan']
    if obs.get('observed_history'):result['history']=obs['observed_history']
    return readable(result),readable(actions)
