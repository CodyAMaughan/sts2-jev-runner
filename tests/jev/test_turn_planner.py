import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from turn_planner import plan

def strike(i,hand,target=0,dmg=6):return {'id':i,'option':{'action':'play_card','hand_index':hand,'enemy_index':target,'card':{'id':'STRIKE_IRONCLAD','type':'Attack','cost':1,'text':'Deal 6 damage.','variables':{'Damage':6},'preview_damage_per_hit':dmg}}}
def defend(i,hand):return {'id':i,'option':{'action':'play_card','hand_index':hand,'enemy_index':-1,'card':{'id':'DEFEND_IRONCLAD','type':'Skill','cost':1,'text':'Gain 5 Block.','variables':{'Block':5}}}}
END={'id':'end','option':{'action':'end_turn'}}
def enemy(name,hp,intent,powers=()):return {'creature':{'name':name,'hp':hp,'max_hp':max(hp,40),'block':0,'powers':[{'id':p,'amount':a,'text':''} for p,a in powers]},'intents':[{'type':'Attack','total_damage':intent}]}
def obs(actions,enemies,energy=3,hp=50):
    deck=[{'id':'STRIKE_IRONCLAD','type':'Attack','cost':1,'variables':{'Damage':6},'text':'Deal 6 damage.'}]*5+[{'id':'DEFEND_IRONCLAD','type':'Skill','cost':1,'variables':{'Block':5},'text':''}]*5
    return {'kind':'combat','actions':actions+[END],'state':{'energy':energy,'player':{'hp':hp,'block':0,'powers':[]},'enemies':enemies,'hand':[],'deck':deck}}

class TurnPlanner(unittest.TestCase):
    def test_finds_lethal_over_ending_turn(self):
        r=plan(obs([strike('a',0),strike('b',1)],[enemy('X',12,20)]))
        self.assertEqual(r['best_hp_now'],0);self.assertEqual(len(r['best_plan']),2);self.assertLess(r['scores']['a'],r['scores']['end'])
    def test_blocks_a_one_off_spike_from_a_low_damage_enemy(self):
        e=enemy('X',200,20);e['creature']['max_hp']=40  # prior ~6/turn
        r=plan(obs([strike('a',0),defend('d',1)],[e],energy=1),history={'X':[5,5,20]})
        self.assertEqual(r['best_plan'],['d'])
    def test_killing_an_attacker_removes_its_hit(self):
        r=plan(obs([strike('a',0,target=0),strike('b',0,target=1)],[enemy('A',6,15),enemy('B',40,5)],energy=1))
        self.assertEqual(r['best_plan'],['a']);self.assertEqual(r['best_hp_now'],5)
    def test_slippery_caps_each_hit(self):
        r=plan(obs([strike('a',0)],[enemy('V',10,0,[('SLIPPERY_POWER',3)])],energy=1))
        self.assertGreater(r['scores']['a'],0)  # 6 damage becomes 1 HP: no kill
    def test_survival_beats_damage_math(self):
        # 12 HP facing 15: the Defend line survives, the Strike line (better "damage math") dies
        r=plan(obs([strike('a',0),defend('d',1)],[enemy('X',30,15)],energy=1,hp=12),history={'X':[30,30,30]})
        self.assertEqual(r['best_plan'],['d'])
    def test_defers_on_unmodelled_powers(self):
        self.assertFalse(plan(obs([strike('a',0)],[enemy('P',21,16,[('ILLUSION_POWER',1)])]))['supported'])

if __name__=='__main__':unittest.main()
