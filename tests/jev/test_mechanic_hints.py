import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from strategy_registry import Strategy,version_packet
ROOT=Path(__file__).resolve().parents[2]
class MechanicHints(unittest.TestCase):
 def setUp(self):
  self.strategy=Strategy(version_packet('1.1.5'))
  self.rows={str(r.get('decision_id')):r for l in (ROOT/'docs/playtests/runs/jev-ironclad-overgrowth-v114-01/jev-decisions.jsonl').read_text().splitlines() if (r:=json.loads(l)).get('kind')=='decision'}
 def hints(self,n):return self.strategy.prompt(self.rows[str(n)]['observation'],'ironclad')[1]['addenda']
 def test_weak_and_vulnerable_on_boss_turn(self):
  hints=' '.join(self.hints(186));self.assertIn('Weak: normally 25%',hints);self.assertIn('Vulnerable: normally 50%',hints)
 def test_speed_warning_when_no_energy(self):self.assertIn('Energy 0 with no free Block', ' '.join(self.hints(58)))
 def test_no_definitions_from_deck_or_discard(self):
  o={'kind':'combat','state':{'room':'Monster','energy':0,'discard':[{'text':'Weak Vulnerable Exhaust Wound'}],'deck':[{'text':'Speed Potion'}]},'actions':[{'id':'a0','option':{'action':'end_turn'}}]}
  text=' '.join(self.strategy.prompt(o,'ironclad')[1]['addenda'])
  self.assertNotIn('Weak: normally',text);self.assertNotIn('Vulnerable: normally',text);self.assertNotIn('Exhaust removes',text)
 def test_selection_source_supplies_exhaust_hint(self):self.assertIn('Exhaust removes',' '.join(self.hints(192)))
 def test_current_turn_potion_advice(self):
  self.assertIn('CURRENT TURN: no Block card is playable', ' '.join(self.hints(58)))
  self.assertIn('at least 20 damage exceeds your Block', ' '.join(self.hints(186)))
 def test_old_strategy_has_no_new_hints(self):
  text=' '.join(Strategy(version_packet('1.1.4')).prompt(self.rows['186']['observation'],'ironclad')[1]['addenda']);self.assertNotIn('Weak: normally',text)
