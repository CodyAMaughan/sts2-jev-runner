"""Content-addressed strategy packets. A run freezes the full module catalog."""
from dataclasses import dataclass
from pathlib import Path
import copy,hashlib,json,os

ROOT=Path(__file__).resolve().parent.parent

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

@dataclass(frozen=True)
class StrategyModule:
    id:str
    name:str
    version:str
    priority:int
    match:dict
    prompt:str
    rationale:str
    category:str="Other decisions"
    act:int=0
    region:str="All acts / fallback"
    encounter:str=""
    def matches(self,obs):
        state=obs['state'];game=state.get('game',state)
        enemies={e.get('creature',{}).get('name','') for e in game.get('enemies') or []}
        for key,value in self.match.items():
            if key=='kind' and obs['kind'] not in value:return False
            if key=='room' and game.get('room') not in value:return False
            if key=='enemy_any' and not enemies.intersection(value):return False
            if key=='min_enemies' and len(game.get('enemies') or [])<value:return False
            if key=='event_id' and state.get('event_id',game.get('event_id')) not in value:return False
        return True

class Strategy:
    def __init__(self,packet):
        self._packet=copy.deepcopy(packet)
        self.modules=tuple(StrategyModule(**m) for m in packet['modules'])
        if len({m.id for m in self.modules})!=len(self.modules):raise ValueError('Duplicate strategy module')
        for m in self.modules:
            if set(m.match)-{'kind','room','enemy_any','min_enemies','event_id'}:raise ValueError('Unknown strategy matcher')
        self.sha256=digest(self._packet)
    @classmethod
    def load(cls,goal=None,profile='balanced'):
        packet=version_packet(os.environ.get('DEALMAKER_STRATEGY_VERSION','1.1.0'))
        if goal is not None:packet['goal']=goal
        packet['profile']=profile
        # Freeze actual prompt-generation source as well as prose; later edits must
        # not retroactively change which packet a historical run reports.
        packet['prompt_builder']={name:(ROOT/'scripts'/name).read_text() for name in ('decision_prompts.py','strategy_registry.py','compact_decisions.py','decision_memory.py','jev_playtest.py')}
        return cls(packet)
    @property
    def packet(self):return copy.deepcopy(self._packet)
    def save(self,path):
        path=Path(path)
        with path.open('x') as f:json.dump({'sha256':self.sha256,'packet':self._packet},f,indent=2)
    def select(self,obs):
        matches=sorted((m for m in self.modules if m.matches(obs)),key=lambda m:(-m.priority,m.id))
        if not matches:raise ValueError('No strategy fallback for '+obs['kind'])
        module=matches[0]
        return module,{'packet_sha256':self.sha256,'strategy_id':self._packet['id'],'strategy_version':self._packet['version'],
                       'module_id':module.id,'module_version':module.version,'route':'deterministic','matched':module.match}
    def prompt(self,obs,character=None):
        module,selection=self.select(obs)
        advice=self._packet.get('character_advice',{}).get(character,{})
        game=obs['state'].get('game',obs['state'])
        held={p.get('id') for p in game.get('potions',[]) if p}
        additions=[]
        if obs['kind']=='combat' and self._packet.get('combat_basics'):
            additions.append(self._packet['combat_basics'])
        if held and obs['kind'] in {'combat','rewards','shop','map'} and advice:
            additions.append(advice['potion_policy'])
            if obs['kind']=='combat':
                additions += [g['advice'] for g in advice['groups'] if held.intersection(g['ids'])]
        turn_advice=self._packet.get('turn_advice',{})
        if obs['kind']=='combat' and turn_advice:
            incoming=sum(i.get('total_damage',0) for e in game.get('enemies') or [] for i in e.get('intents',[]))
            energy=game.get('energy',0)
            hp=game.get('player',{}).get('hp',0)
            block=game.get('player',{}).get('block',0)
            hand=[h['card'] for h in game.get('hand') or []]
            slippery=any(p.get('id')=='SLIPPERY_POWER' and p.get('amount',0)>0 for e in game.get('enemies') or [] for p in e['creature'].get('powers',[]))
            block_available=any(a['option'].get('action')=='play_card' and a['option'].get('card',{}).get('variables',{}).get('Block',0)>0 for a in obs['actions'])
            # The numeric survival check is evaluated first and independently of whether a
            # Block card is in hand: a missing Block card is exactly when a held potion or
            # accepting the hit is the only lever, so it must never be masked by 'no_block'.
            # Opt-in per packet: older versions lack these keys and are unaffected.
            deficit=incoming-block
            risk_key=None
            if hp>0 and incoming>block:
                if deficit>=hp:risk_key='lethal_risk'
                elif deficit>=hp*0.5:risk_key='severe_risk'
            if risk_key and turn_advice.get(risk_key):
                potions=', '.join(sorted(held)) if held else 'none'
                additions.append(turn_advice[risk_key].format(incoming=incoming,hp=hp,block=block,deficit=deficit,potions=potions))
            if slippery and turn_advice.get('slippery'):additions.append(turn_advice['slippery'])
            elif not block_available and turn_advice.get('no_block'):additions.append(turn_advice['no_block'])
            elif incoming==0:additions.append(turn_advice['no_incoming'])
            elif incoming>block and not risk_key:
                additions.append(turn_advice['one_energy'] if energy==1 else turn_advice['under_attack'])
            bash=next((c for c in hand if c.get('id')=='BASH'),None)
            if bash and not (slippery and turn_advice.get('slippery')) and any(c is not bash and c.get('type')=='Attack' and isinstance(c.get('cost'),(int,float)) and isinstance(bash.get('cost'),(int,float)) and 0<=c['cost']<=energy-bash['cost'] for c in hand):
                additions.append(turn_advice['bash_setup'])
            # Multi-enemy targeting is also opt-in per packet.
            template=self._packet.get('multi_enemy_template')
            if template:
                alive=[e for e in game.get('enemies') or [] if e.get('creature',{}).get('hp',0)>0]
                if len(alive)>=2:
                    ranked=sorted(alive,key=lambda e:-sum(i.get('total_damage',0) for i in e.get('intents',[])))
                    top=ranked[0];top_dmg=sum(i.get('total_damage',0) for i in top.get('intents',[]))
                    if top_dmg>0:
                        additions.append(template.format(count=len(alive),top_name=top['creature'].get('name','enemy'),top_dmg=top_dmg,top_hp=top['creature'].get('hp',0)))
        # Only visible, immediately relevant objects trigger definitions: never the whole deck.
        if self._packet.get('mechanic_hints'):
            import re
            objects=[a.get('option',{}) for a in obs.get('actions',[])]
            objects.append(obs['state'].get('source') or {})
            if obs['kind']=='combat':
                objects += [h['card'] for h in game.get('hand') or []]
                objects += list(game.get('potions') or [])
                objects += list(game.get('player',{}).get('powers') or [])
                objects += [p for e in game.get('enemies') or [] for p in e.get('creature',{}).get('powers') or []]
            if obs['kind']=='combat' and self._packet.get('current_turn_hints'):
                opts=[a['option'] for a in obs.get('actions',[])]
                block_cards=[o for o in opts if o.get('action')=='play_card' and (o.get('card') or {}).get('variables',{}).get('Block',0)>0]
                incoming=sum(i.get('total_damage',0) for e in game.get('enemies') or [] for i in e.get('intents',[]))
                if 'SPEED_POTION' in held and not block_cards:
                    additions.append(self._packet['current_turn_hints']['no_speed_target'])
                if 'WEAK_POTION' in held and incoming-game.get('player',{}).get('block',0)>=20:
                    additions.append(self._packet['current_turn_hints']['large_attack_weak'])
            visible=json.dumps(objects).lower()
            for hint in self._packet['mechanic_hints']:
                if obs['kind'] in hint['kinds'] and any(re.search(r'(?<![a-z])'+re.escape(term)+r'(?![a-z])',visible) for term in hint['terms']):
                    additions.append(hint['text'])
        plan=obs.get('run_plan',{})
        if obs['kind'] in {'card_reward','choose_card','bundle','shop','rest','map','upgrade'}:
            boss_advice=self._packet.get('boss_plans',{}).get(plan.get('known_boss'))
            if boss_advice:additions.append(boss_advice)
        selection['addenda']=additions
        return '\n'.join([self._packet['goal'],module.prompt,*additions]),selection

def version_packet(version):
    import re
    if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Invalid strategy version')
    return json.loads((ROOT/'strategies/balanced'/f'{version}.json').read_text())

def require_approved(version=None):
    packet=version_packet(version or os.environ.get('DEALMAKER_STRATEGY_VERSION','1.1.0'))
    approvals=json.loads((ROOT/'strategies/approvals.json').read_text())
    if digest(packet) not in approvals:raise ValueError('Strategy is not approved. Review its diff before authorizing a run.')

def strategy_diff(before,after):
    import difflib
    a=version_packet(before);b=version_packet(after)
    def display(value):
        return value if isinstance(value,str) else json.dumps(value,indent=2) if value is not None else ''
    def field_diff(key,left,right):
        import re
        l=re.findall(r'\s+|[^\s]+',display(left));r=re.findall(r'\s+|[^\s]+',display(right))
        ls=[];rs=[]
        for tag,i,j,x,y in difflib.SequenceMatcher(None,l,r,autojunk=False).get_opcodes():
            ls.append({'text':''.join(l[i:j]),'changed':tag!='equal'})
            rs.append({'text':''.join(r[x:y]),'changed':tag!='equal'})
        return {'field':key,'left':ls,'right':rs}
    sections=[]
    package=[field_diff(k,a.get(k),b.get(k)) for k in ('name','version','description','goal','prompt_format') if a.get(k)!=b.get(k)]
    if package:sections.append({'id':'package','name':'Package details','status':'modified','metadata':True,'fields':package})
    for key,name in [('current_turn_hints','Current-turn potion tactics'),('mechanic_hints','Conditional mechanic definitions and tactics'),('planning_context','Run-planning context enabled'),('boss_plans','Boss-specific drafting and potion plans'),('turn_advice','Turn-specific advice routing'),('combat_basics','Combat decision fundamentals'),('observation_policy','Observed decision history'),('character_advice','Ironclad potion priorities'),('compression_contract','Context compression and tradeoffs'),('multi_enemy_template','Multi-enemy targeting hint')]:
        if a.get(key)!=b.get(key):sections.append({'id':key,'name':name,'status':'modified','fields':[field_diff(key,a.get(key),b.get(key))]})
    left={m['id']:m for m in a['modules']};right={m['id']:m for m in b['modules']}
    unchanged=0
    for key in dict.fromkeys([*right,*left]):
        l=left.get(key,{});r=right.get(key,{})
        if l==r:unchanged+=1;continue
        fields=[field_diff(k,l.get(k),r.get(k)) for k in ('prompt','rationale','match','priority','name','version','category','act','region','encounter') if l.get(k)!=r.get(k)]
        sections.append({'id':key,'name':r.get('name',l.get('name',key)),'status':'added' if not l else 'removed' if not r else 'modified','fields':fields})
    return {'before':before,'after':after,'sections':sections,'unchanged_modules':unchanged,
            'diff':'\n'.join(difflib.unified_diff(json.dumps(a,indent=2).splitlines(),json.dumps(b,indent=2).splitlines(),fromfile=before,tofile=after,lineterm=''))}

def catalog():
    active=Strategy.load();entries=[]
    approvals=json.loads((ROOT/'strategies/approvals.json').read_text())
    for path in sorted((ROOT/'strategies/balanced').glob('*.json'),reverse=True):
        p=json.loads(path.read_text());sha=active.sha256 if p['version']==active.packet['version'] else digest(p)
        entries.append({**p,'sha256':sha,'approval':approvals.get(digest(p)),
          'selection_order':['Exact encounter','Encounter group','Boss / elite / normal fallback','Decision-type fallback','Generic fallback'],
          'model_router':{'enabled':False}})
    return entries
