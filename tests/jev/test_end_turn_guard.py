import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from jev_playtest import wasted_energy_note

def card(i,type_,text,cost=1):return {'id':i,'option':{'action':'play_card','card':{'type':type_,'text':text,'cost':cost}}}
END={'id':'e','option':{'action':'end_turn'}}

def obs(energy,cards,intent=10,block=0,powers=()):
    return {'kind':'combat','actions':cards+[END],'state':{'energy':energy,'player':{'block':block},
        'enemies':[{'creature':{'powers':[{'id':p} for p in powers]},'intents':[{'type':'Attack','total_damage':intent}]}]}}

class EndTurnGuard(unittest.TestCase):
    def test_unspent_energy_with_block_against_hit(self):
        self.assertIn('10 incoming',wasted_energy_note(obs(1,[card('d','Skill','Gain 5 Block.')]),'e'))
    def test_attack_left_triggers(self):
        self.assertIsNotNone(wasted_energy_note(obs(2,[card('s','Attack','Deal 6 damage.')],intent=0),'e'))
    def test_block_without_incoming_does_not_trigger(self):
        self.assertIsNone(wasted_energy_note(obs(1,[card('d','Skill','Gain 5 Block.')],intent=0),'e'))
    def test_reactive_power_allows_holding_attacks(self):
        self.assertIsNone(wasted_energy_note(obs(1,[card('s','Attack','Deal 6.')],intent=0,powers=['THORNS_POWER']),'e'))
    def test_no_energy_or_not_end_turn(self):
        self.assertIsNone(wasted_energy_note(obs(0,[card('s','Attack','Deal 6.',0)]),'e'))
        self.assertIsNone(wasted_energy_note(obs(1,[card('s','Attack','Deal 6.')]),'s'))
    def test_unaffordable_card_ignored(self):
        self.assertIsNone(wasted_energy_note(obs(1,[card('b','Attack','Deal 32.',2)]),'e'))

if __name__=='__main__':unittest.main()
