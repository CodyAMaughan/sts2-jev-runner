import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from strategy_registry import Strategy,digest
import jev_playtest as pilot
import mission_control as mc
class Strategies(unittest.TestCase):
 def setUp(self):self.strategy=Strategy.load()
 def obs(self,room='Monster',enemies=('NIBBIT',),kind='combat'):
  return {'kind':kind,'state':{'room':room,'enemies':[{'creature':{'name':n}} for n in enemies]},'actions':[{'id':'a0','option':{'action':'end_turn'}}]}
 def test_exact_boss_wins(self):self.assertEqual(self.strategy.select(self.obs('Boss',('CRUSHER','ROCKET')))[0].id,'boss.kaiser-crab')
 def test_exact_elite_matches_actual_monster(self):self.assertEqual(self.strategy.select(self.obs('Elite',('PHROG_PARASITE',)))[0].id,'elite.phrog-parasite')
 def test_unknown_boss_falls_back(self):self.assertEqual(self.strategy.select(self.obs('Boss',('UNKNOWN',)))[0].id,'combat.boss')
 def test_elite_not_misrouted_to_group(self):self.assertEqual(self.strategy.select(self.obs('Elite',('A','B')))[0].id,'combat.elite')
 def test_normal_group_and_event_fallback(self):
  self.assertEqual(self.strategy.select(self.obs(enemies=('A','B')))[0].id,'combat.group')
  self.assertEqual(self.strategy.select(self.obs(kind='event'))[0].id,'event.generic')
 def test_packet_is_detached_and_changes_content_hash(self):
  original=self.strategy.sha256;p=self.strategy.packet;p['modules'][0]['prompt']='new'
  self.assertEqual(self.strategy.sha256,original);self.assertNotEqual(Strategy(p).sha256,original)
 def test_controller_freezes_packet_and_route(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'jev-decisions.jsonl';obs={**self.obs(),'status':'decision','decision_id':'1'}
   with patch.dict(os.environ,{'DEALMAKER_BRIDGE_TOKEN':'x'*30}),patch.object(sys,'argv',['pilot','--mock','--max-decisions','1','--log',str(path)]),patch.object(pilot,'request',side_effect=[obs,{'accepted':True}]):pilot.main()
   packet=json.loads((path.parent/'strategy-packet.json').read_text());rows=[json.loads(l) for l in path.read_text().splitlines()]
   self.assertEqual(packet['sha256'],digest(packet['packet']));self.assertEqual(rows[1]['strategy_selection']['packet_sha256'],packet['sha256']);self.assertEqual(rows[1]['strategy_selection']['module_id'],'combat.normal')
 def test_historical_elapsed_and_legacy_not_rewritten(self):
  root=Path(__file__).resolve().parents[2]
  s=mc.run_summary(root/'docs/playtests/runs/jev-donaldtrump-headed-01')
  self.assertGreater(s['elapsed'],0);self.assertGreater(s['model_seconds'],0);self.assertIsNone(s['strategy_packet_sha256'])
 def test_complete_installed_encounter_coverage_and_routing(self):
  import re
  source=Path(__file__).resolve().parents[2]/'.tooling/game-src'
  expected={p.stem for p in (source/'MegaCrit.Sts2.Core.Models.Encounters').glob('*.cs') if re.search(r'RoomType\s*=>\s*RoomType\.(Boss|Elite)',p.read_text())}
  exact=[m for m in self.strategy.modules if m.encounter]
  self.assertEqual(len(exact),24);self.assertEqual({m.encounter for m in exact},expected)
  for m in exact:
   self.assertIn(m.act,(1,2,3));self.assertIn(m.category,('Boss prompts','Elite prompts'))
   for enemy in m.match['enemy_any']:
    with self.subTest(encounter=m.encounter,enemy=enemy):
     self.assertEqual(self.strategy.select(self.obs(m.match['room'][0],(enemy,)))[0].id,m.id)
 def test_old_packet_still_loads(self):
  p=Path(__file__).resolve().parents[2]/'strategies/balanced/1.0.0.json'
  self.assertEqual(Strategy(json.loads(p.read_text())).select(self.obs())[0].id,'combat.normal')
 def test_context_contract_examples_use_actual_projection(self):
  from context_contracts import contracts
  from decision_prompts import COMBAT,RUN
  contracts=contracts()
  self.assertEqual({f['name'] for f in contracts['combat']['fields']},set(COMBAT)|{'prompt','source','min','max','selected'})
  self.assertEqual({f['name'] for f in contracts['shop']['fields']},set(RUN)|{'prompt','source','min','max','selected'})
  for kind,c in contracts.items():
   request=c['example'];state=request['state']['decision']['state']
   self.assertLessEqual(set(state),{f['name'] for f in c['fields']})
   self.assertNotIn('screen',state);self.assertNotIn('map',state)
   self.assertTrue(request['questions']['action']['criteria'])
  self.assertIn('enemies',contracts['card_selection:combat']['example']['state']['decision']['state'])
  self.assertNotIn('enemies',contracts['card_selection']['example']['state']['decision']['state'])
  self.assertIn('routes',contracts['map']['example']['state']['decision']['state'])
 def test_diff_and_approval_gate(self):
  import strategy_registry as registry
  diff=registry.strategy_diff('1.0.0','1.1.0')['diff']
  self.assertIn('+',diff);self.assertIn('Personal Hive',diff)
  registry.require_approved()
  changed=registry.version_packet('1.1.0');changed['modules'][0]['prompt']+=' unreviewed'
  with patch.object(registry,'version_packet',return_value=changed):
   with self.assertRaisesRegex(ValueError,'not approved'):registry.require_approved()
  with self.assertRaises(ValueError):registry.strategy_diff('../bad','1.1.0')
 def test_side_by_side_diff_preserves_prompt_text(self):
  from strategy_registry import strategy_diff,version_packet
  diff=strategy_diff('1.1.0','1.1.1')
  modules=[s for s in diff['sections'] if not s.get('metadata')]
  self.assertEqual(len(modules),3);self.assertEqual(diff['unchanged_modules'],34)
  for version,side in [('1.1.0','left'),('1.1.1','right')]:
   original={m['id']:m for m in version_packet(version)['modules']}
   for section in modules:
    prompt=next(f for f in section['fields'] if f['field']=='prompt')
    self.assertEqual(''.join(p['text'] for p in prompt[side]),original[section['id']]['prompt'])
  self.assertEqual(strategy_diff('1.1.1','1.1.1')['sections'],[])
