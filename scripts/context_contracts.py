"""Dashboard documentation derived from the live projection, with illustrative requests."""
from decision_prompts import COMBAT,RUN,DRAFT,SELECTION
from jev_playtest import make_request

DESCRIPTIONS={
 'player':'Combat: name, HP, maximum HP, Block and powers (id, amount, text). Outside combat: only hp and max_hp.',
 'energy':'Current spendable energy. Legal action costs are also present in the offered actions.',
 'turn':'Current combat turn.', 'boast':'Active Boast stacks, when provided.', 'boast_attacks':'Attacks counted toward fulfilling Boast, when provided.',
 'hand':'Ordered hand positions: index and card_ref. Card definitions contain id, name, type, cost, upgraded, text, keywords, variables and damage preview when available.',
 'draw_pile_unordered':'Unordered card_ref/count pairs. No future draw order.', 'discard':'Card_ref/count pairs in discard.', 'exhaust':'Card_ref/count pairs in exhaust.',
 'deck':'Permanent deck as card_ref/count pairs, preserving upgrades and distinct variants.',
 'relics':'Owned relic IDs and effect text, with any additional fields supplied by the bridge.',
 'potions':'Potion inventory and effect details supplied by the bridge; indexed empty slots are preserved.',
 'enemies':'Enemy index, creature name/HP/max_hp/Block/powers and intents (type, total_damage and any available intent details).',
 'stars':'Regent resource, if provided.', 'orb_slots':'Defect orb capacity, if provided.', 'orbs_in_order':'Ordered Defect orb data, if provided.', 'osty':'Necrobinder pet state, if provided.',
 'floor':'Current floor.', 'act':'Current act.', 'gold':'Current gold.',
 'routes':'Map only: reachable future nodes, room types and next-node connections. Past and unreachable nodes omitted.',
 'prompt':'Pending choice instructions when supplied; event/selection screen text replaces this for supported narrative decisions.',
 'source':'Originating card/effect when supplied for a pending choice.', 'min':'Minimum selection count, when supplied.', 'max':'Maximum selection count, when supplied.', 'selected':'Already selected choices, when supplied.'}

NARRATIVE={'event','crystal_sphere','simple_select','deck_select','transform','enchant','choose_card','bundle'}

def contracts(version="1.1.0"):
 from strategy_registry import version_packet
 fmt=version_packet(version).get("prompt_format","decision-v2")
 result={}
 for kind in sorted(DRAFT|SELECTION|{'combat','map','rewards'}):
  for combat in ([False,True] if kind in SELECTION else [kind=='combat']):
   keys=list(COMBAT if combat else ('player','gold','relics','potions') if kind=='rewards' else RUN)
   if kind=='map':keys.append('routes')
   keys+=['prompt','source','min','max','selected']
   # Illustrative values go through the actual request builder, never a model call.
   sample={key:1 for key in set(COMBAT)|set(RUN)}
   sample.update(player={'hp':42,'max_hp':75,'block':0},hand=[],deck=[],draw_pile_unordered=[],discard=[],exhaust=[],enemies=[{'creature':{'name':'ILLUSTRATIVE_ENEMY','hp':30,'max_hp':30,'block':0},'index':0,'intents':[{'type':'Attack','total_damage':10}]}] if combat else [])
   card={'id':'EXAMPLE_STRIKE','name':'Example Strike','type':'Attack','cost':1,'text':'Deal 6 damage.','upgraded':False}
   sample.update(hand=[{'index':0,'card':card}],deck=[card,card],draw_pile_unordered=[card],relics=[],potions=[],energy=3,turn=1,gold=99,act=1,floor=4)
   # No invented character resources in the example. The field contract still lists conditional resources.
   for key in ('boast','boast_attacks','stars','orb_slots','orbs_in_order','osty'):sample.pop(key,None)
   option={'action':'end_turn'} if combat and kind=='combat' else {'action':'illustrative_choice','text':'Sample legal choice; actual choices come from the game'}
   state={'game':sample}
   if kind in SELECTION or kind in NARRATIVE:state.update(prompt='Illustrative pending choice. Actual rules are supplied by the game.',source='Example effect',min=1,max=1,selected=[])
   if kind=='map':
    state['map']=[{'row':2,'col':1,'type':'Monster','children':[]}];option={'action':'map','row':2,'col':1}
   obs={'kind':kind,'state':state,'actions':[{'id':'a0','option':option}]}
   if kind=='combat':obs['actions'].insert(0,{'id':'a1','option':{'action':'play_card','hand_index':0,'enemy_index':0,'card':card}})
   name=kind+(':combat' if combat and kind in SELECTION else '')
   result[name]={'fields':[{'name':k,'description':DESCRIPTIONS[k]} for k in keys],
    'notes':'Fields appear only when provided and nonempty; zero and false are preserved. Prompt/source/min/max/selected are conditional choice metadata. Raw screen, seed, observation hashes and the full raw observation are not sent. Narrative text is retained only for event and supported selection decisions. All bosses and elites use the same combat fields; their strategy prose differs.',
    'example':make_request(obs,'Global goal + selected module prompt','jev-latest','ironclad',prompt_format=fmt)}
 if fmt=='decision-v3':
  for entry in result.values():
   entry['notes']+=' Decision-v3: combat state is compact text; cards lists full effects only for hand/action cards. Other pile cards retain names/counts. Other decision types keep full deck effects. Ironclad potion advice is added only for held potions.'
 return result
