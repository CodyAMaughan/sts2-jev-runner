import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from decision_prompts import project
from jev_playtest import make_request
class Templates(unittest.TestCase):
 def obs(self,kind,game=None):return {'kind':kind,'state':{'game':game or {'player':{'hp':4,'max_hp':70,'block':9},'gold':0,'energy':0,'enemies':[{'hp':30}],'deck':[]},'screen':'junk','text':'decorative','map':None},'actions':[{'id':'a0','option':{'action':'proceed'}}]}
 def test_rewards_strip_stale_combat_but_keep_zero_gold(self):
  s=project(self.obs('rewards'))['state'];self.assertEqual(s,{'player':{'hp':4,'max_hp':70},'gold':0})
 def test_combat_retains_zero_energy_and_drops_duplicate_deck(self):
  s=project(self.obs('combat'))['state'];self.assertEqual(s['energy'],0);self.assertIn('enemies',s);self.assertNotIn('deck',s);self.assertNotIn('screen',s)
 def test_choice_preserves_constraints_and_source(self):
  o=self.obs('card_selection');o['state'].update(min=0,max=2,selected=[{'name':'A'}],source={'name':'exhaust outlet'},prompt='Exhaust cards')
  s=project(o)['state'];self.assertEqual(s['min'],0);self.assertEqual(s['max'],2);self.assertIn('source',s);self.assertIn('enemies',s)
 def test_map_keeps_reachable_branches_only(self):
  o=self.obs('map');o['actions']=[{'id':'a0','option':{'action':'map','row':1,'col':2}}]
  o['state']['map']=[{'row':0,'col':0,'type':'Monster','children':[]},{'row':1,'col':2,'type':'Rest','children':[{'row':2,'col':2}]},{'row':2,'col':2,'type':'Elite','children':[]},{'row':2,'col':3,'type':'Shop','children':[]}]
  self.assertEqual([n['node'] for n in project(o)['state']['routes']],['1,2','2,2'])
 def test_unknown_kind_stops_instead_of_guessing(self):
  with self.assertRaises(ValueError):project(self.obs('new_kind'))
 def test_archive_projects_without_mutation(self):
  path=Path(__file__).resolve().parents[2]/'docs/playtests/runs/jev-donaldtrump-headed-01/jev-decisions.jsonl'
  for line in path.read_text().splitlines():
   row=json.loads(line)
   if row.get('kind')!='decision':continue
   o=row['observation'];before=json.dumps(o,sort_keys=True);p=make_request(o,'survive','jev-latest')
   self.assertEqual(set(p['questions']['action']['criteria']),{a['id'] for a in o['actions']})
   self.assertEqual(json.dumps(o,sort_keys=True),before)
