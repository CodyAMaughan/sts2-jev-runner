"""Versioned, provider-neutral decision projections. Raw replay evidence is never changed."""
import json,re
from collections import Counter

VERSION='decision-v2'
COMBAT=('player','energy','turn','boast','boast_attacks','hand','draw_pile_unordered','discard','exhaust','relics','potions','enemies','stars','orb_slots','orbs_in_order','osty')
RUN=('floor','act','player','gold','deck','relics','potions')
DRAFT={'card_reward','upgrade','transform','enchant','deck_select','choose_card','bundle','relic','shop','rest','event','treasure','crystal_sphere'}
SELECTION={'card_selection','simple_select'}
INSTRUCTIONS={
 'combat':'Choose the best legal play, potion action, or end turn. Check incoming damage and lethal first.',
 'map':'Choose a route for survival and deck development. Only reachable future nodes are supplied.',
 'rewards':'Claim useful rewards before leaving. Free gold and potions with space are normally worth taking.',
 'card_reward':'Choose a card or skip. Compare its contribution with the current deck; a larger deck is not always better.',
 'shop':'Choose a purchase, potion action, or leave. Weigh removal, synergy, gold and survival.',
 'rest':'Choose healing or improvement based on health, deck and relics.',
 'event':'Compare the stated rewards and costs against health, gold and deck.',
 'card_selection':'Resolve the pending selection using its source, prompt, bounds and already selected cards.',
}

MECHANICS={
 'boast':'Boast N stacks promises and resets progress. Two later attacks this turn grant N Strength; failure puts N Embarrassment atop draw.',
 'wall':'Wall persists between turns; ordinary Block expires.',
 'favor':'Favors Retain; choose damage or Block.',
 'iou':'An IOU in hand prevents non-Spin attacks; settle it for 1 energy.',
 'bargain':'Bargain triggers once per card per combat when another card or Power exhausts it from hand on your turn: play it free, leave it exhausted. Self-exhaust/Ethereal do not trigger it.',
}
def rules_for(obs,character):
    base='Choose one offered action. Card text is authoritative. Draw order and future RNG are unknown.'
    if character=='harry':return base+' Courage persists and comes from cards, powers and relics. Fully blocking attacks does not grant Courage. Conditional Courage spending is automatic if affordable. Rally multiplies marked effects by Rally cards played this turn including the current card. Resourceful N: deliberate discard on your turn draws N after the discard batch; cleanup does not trigger. Dark Arts creates a combat-only Dark Mark in hand after the card resolves. Each held Dark Mark loses 2 HP at end turn, bypassing Block; discarding delays it until reshuffled. Next Rally bonuses and current Courage appear in card text and powers.'
    if character!='dealmaker':return base
    decision=project(obs)
    evidence=json.dumps([decision,obs['actions']]).lower()
    return base+' '+' '.join(text for keyword,text in MECHANICS.items() if keyword in evidence and (obs['kind']!='rewards'))

def clean(v):
    if isinstance(v,str):return re.sub(r'\[/?(?:gold|blue|red|green|purple|orange|gray|b|i)\]','',v)
    if isinstance(v,list):return [clean(x) for x in v] # Keep indexed empty potion slots, etc.
    if isinstance(v,dict):
        return {k:clean(x) for k,x in v.items() if x is not None and x!='' and x!=[] and x!={}}
    return v

def bag(cards):
    values={};counts=Counter()
    for c in cards:
        key=json.dumps(c,sort_keys=True);values[key]=c;counts[key]+=1
    return [dict(card=values[k],count=n) for k,n in counts.items()]

def project(obs):
    kind=obs['kind'];state=obs['state'];game=state.get('game',state)
    combat=kind=='combat' or (kind in SELECTION and bool(game.get('enemies')))
    if combat: keys=COMBAT
    elif kind=='rewards':keys=('player','gold','relics','potions')
    elif kind=='map':keys=RUN
    elif kind in DRAFT or kind in SELECTION:keys=RUN
    else:raise ValueError('No prompt template for decision kind: '+kind)
    context={k:game[k] for k in keys if k in game}
    if not combat and isinstance(context.get('player'),dict):
        context['player']={k:v for k,v in context['player'].items() if k in ('hp','max_hp')}
    for k in ('deck','draw_pile_unordered','discard','exhaust'):
        if k in context:context[k]=bag(context[k])
    # Map: compact reachable future graph, never previous/unreachable nodes or UI text.
    # Keeping connections avoids throwing away the ability to plan beyond one room.
    if kind=='map':
        nodes={(n['row'],n['col']):n for n in state.get('map') or []}
        frontier=[(a['option']['row'],a['option']['col']) for a in obs['actions'] if a['option'].get('action')=='map'];reachable=set()
        while frontier:
            key=frontier.pop()
            if key in reachable or key not in nodes:continue
            reachable.add(key);frontier += [(c['row'],c['col']) for c in nodes[key].get('children',[])]
        context['routes']=[{'node':f'{r},{c}','type':nodes[r,c]['type'],'next':[f"{n['row']},{n['col']}" for n in nodes[r,c].get('children',[])]} for r,c in sorted(reachable)]
    for k in ('prompt','source','min','max','selected','upgrades'):
        if k in state:context[k]=state[k]
    # Events/selection screens may contain unique rules not repeated in options.
    if kind in {'event','crystal_sphere','simple_select','deck_select','transform','enchant','choose_card','bundle'} and state.get('text'):
        context['prompt']=state['text']
    return {'kind':kind,'state':clean(context)}

def build(obs,strategy,character,rules,prompt_format=None):
    import os
    from strategy_registry import version_packet
    if (prompt_format or version_packet(os.environ.get("DEALMAKER_STRATEGY_VERSION","1.1.0")).get("prompt_format"))=="decision-v3":
        from compact_decisions import build as compact_build
        return compact_build(obs,strategy,character,rules)
    decision=project(obs);definitions={};references={}
    def compact(v):
        if isinstance(v,list):return [compact(x) for x in v]
        if not isinstance(v,dict):return v
        if {'id','name','type','text','cost'}<=v.keys():
            v=clean(v);key=json.dumps(v,sort_keys=True,separators=(',',':'))
            if key not in references:
                ref='c'+str(len(references));references[key]=ref;definitions[ref]=v
            return {'card_ref':references[key]}
        return {k:compact(x) for k,x in clean(v).items()}
    decision=compact(decision)
    actions={}
    for a in obs['actions']:
        option=dict(a['option'])
        if isinstance(option.get('enemy_index'),int) and option['enemy_index']>=0 and obs['kind'] in {'combat','card_selection'}:
            option.pop('target',None)
        actions[a['id']]=compact(option)
    return {'rules':rules,'strategy':strategy,'character':character,'format':VERSION+'; card_ref uses card_definitions; omitted collections are empty; unordered piles list card/count; enemy_index refers to enemies.',
            **({'card_definitions':definitions} if definitions else {}),'decision':decision},actions
