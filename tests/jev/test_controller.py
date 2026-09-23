import importlib.util,json,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
spec=importlib.util.spec_from_file_location('pilot',Path(__file__).resolve().parents[2]/'scripts/jev_playtest.py')
pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)
class ControllerTests(unittest.TestCase):
 def setUp(self):
  self.obs={'decision_id':'17','kind':'combat','state':{'player':{'hp':3}},'actions':[{'id':'a0','option':{'action':'play_card','enemy_index':1}},{'id':'a1','option':{'action':'end_turn'}}]}
 def test_criteria_preserves_targets(self):
  req=pilot.make_request(self.obs,'survive','jev-latest');self.assertEqual(json.loads(req['questions']['action']['criteria']['a0'])['enemy_index'],1)
 def test_state_and_strategy_in_request(self):
  req=pilot.make_request(self.obs,'wall experiment','pinned-model');self.assertEqual(req['model'],'pinned-model');self.assertEqual(req['state']['strategy'],'wall experiment');self.assertEqual(req['state']['decision'],{'kind':'combat','state':self.obs['state']})
 def test_compact_cards_preserve_variants_and_original(self):
  card={'id':'STRIKE','name':'Strike','type':'Attack','text':'Deal 6 damage.','cost':1,'preview_damage_per_hit':6}
  upgraded={**card,'cost':0,'preview_damage_per_hit':9}
  self.obs['state']={'deck':[card,card],'hand':[card,upgraded]}
  self.obs['actions'][0]['option']['card']=upgraded
  before=json.dumps(self.obs,sort_keys=True)
  req=pilot.make_request(self.obs,'survive','jev-latest');defs=req['state']['card_definitions']
  self.assertEqual(len(defs),2)
  def expand(v):
   if isinstance(v,list):return [expand(x) for x in v]
   if isinstance(v,dict):return defs[v['card_ref']] if set(v)=={'card_ref'} else {k:expand(x) for k,x in v.items()}
   return v
  self.assertEqual(expand(req['state']['decision']['state']),{'hand':self.obs['state']['hand']})
  self.assertEqual(expand(json.loads(req['questions']['action']['criteria']['a0'])),self.obs['actions'][0]['option'])
  self.assertEqual(json.dumps(self.obs,sort_keys=True),before)
 def test_legal_response(self):
  self.assertEqual(pilot.parse_answer({'answers':{'action':{'type':'choice','choice':'a1'}}},self.obs),'a1')
 def test_hallucinated_action_rejected(self):
  with self.assertRaises(ValueError):pilot.parse_answer({'answers':{'action':{'type':'choice','choice':'a99'}}},self.obs)
 def test_wrong_primitive_rejected(self):
  with self.assertRaises(ValueError):pilot.parse_answer({'answers':{'action':{'type':'score','choice':'a0'}}},self.obs)
 def test_duplicate_ids_rejected(self):
  self.obs['actions'][1]['id']='a0'
  with self.assertRaises(ValueError):pilot.make_request(self.obs,'x','y')
 def test_large_action_sets_not_truncated(self):
  self.obs['actions']=[{'id':str(i),'option':{}} for i in range(256)]
  with self.assertRaises(ValueError):pilot.make_request(self.obs,'x','y')
 def test_replay_fingerprint_changes_on_state_or_options(self):
  before=pilot.fingerprint(self.obs);self.obs['state']['hp']=4;self.assertNotEqual(before,pilot.fingerprint(self.obs))
 def test_fingerprint_stable_under_key_order(self):
  self.assertEqual(pilot.fingerprint(self.obs),pilot.fingerprint(dict(reversed(list(self.obs.items())))))
 def test_replay_ignores_only_map_decoration(self):
  self.obs['state']={'screen':'NMapScreen','text':'Legend','game':{'hp':4},'map':[1,2]}
  before=pilot.replay_fingerprint(self.obs);self.obs['state']['text']='Legend | Act 1 | Overgrowth'
  self.assertEqual(before,pilot.replay_fingerprint(self.obs))
  self.obs['state']['game']['hp']=3;self.assertNotEqual(before,pilot.replay_fingerprint(self.obs))
if __name__=='__main__':unittest.main()
