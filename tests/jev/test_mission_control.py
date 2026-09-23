import importlib.util,sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import mission_control as mc
import jev_playtest as pilot

class MissionTests(unittest.TestCase):
 def test_run_path_rejects_traversal(self):
  for name in ['../.env.local','/tmp','x/y','..']:
   with self.assertRaises(ValueError):mc.run_dir(name)
 def test_base_character_prompt_has_no_dealmaker_rules(self):
  obs={'kind':'combat','state':{},'actions':[{'id':'a0','option':{'action':'end_turn'}}]}
  for character in mc.CHARACTERS[1:]:
   req=pilot.make_request(obs,'survive','jev-1.13.0',character)
   self.assertIn(character,req['state']['character']);self.assertNotIn('Boast',req['state']['rules'])
 def test_null_response_and_reward_skip(self):
  row={'decision_id':'2','action_id':'a1','observation':{'kind':'rewards','state':{'game':{'floor':2}},'actions':[{'id':'a0','option':{'action':'claim_reward','text':'Potion'}},{'id':'a1','option':{'action':'proceed'}}]},'source':'sole_legal_action','response':None}
  result=mc.step_summary(row);self.assertEqual(result['skipped'],['Potion']);self.assertEqual(result['input_tokens'],0)

if __name__=='__main__':unittest.main()
