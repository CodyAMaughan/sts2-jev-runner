import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from compact_decisions import build
from strategy_registry import Strategy,version_packet,require_approved
ROOT=Path(__file__).resolve().parents[2]
class Compact(unittest.TestCase):
 def test_recorded_actions_and_raw_evidence_preserved(self):
  for line in (ROOT/'docs/playtests/runs/jev-ironclad-overgrowth-v111-02/jev-decisions.jsonl').read_text().splitlines():
   r=json.loads(line)
   if r.get('kind')!='decision':continue
   obs=r['observation'];before=copy.deepcopy(obs)
   state,actions=build(obs,'survive','ironclad','rules')
   self.assertEqual(set(actions),{a['id'] for a in obs['actions']})
   self.assertEqual(obs,before)
   for a in obs['actions']:
    op=a['option']
    if op['action']=='play_card':
     self.assertIn('h'+str(op['hand_index']),actions[a['id']])
     if op.get('enemy_index',-1)>=0:self.assertIn('e'+str(op['enemy_index']),actions[a['id']])
 def test_conditional_potion_advice_and_character_isolation(self):
  s=Strategy(version_packet('1.1.2'));o={'kind':'combat','state':{'room':'Elite','potions':[{'id':'SPEED_POTION'}]},'actions':[]}
  prompt,selection=s.prompt(o,'ironclad');self.assertIn('expires this turn',prompt);self.assertNotIn('retrieval',prompt)
  self.assertTrue(selection['addenda']);self.assertFalse(s.prompt(o,'silent')[1]['addenda'])
 def test_unreviewed_edits_remain_blocked(self):
  packet=version_packet('1.1.2');packet['goal']+=' UNREVIEWED EDIT'
  with patch('strategy_registry.version_packet',return_value=packet):
   with self.assertRaises(ValueError):require_approved('1.1.2')
 def test_versioned_context_examples(self):
  from context_contracts import contracts
  old=contracts('1.1.1')['combat']['example'];new=contracts('1.1.2')['combat']['example']
  self.assertIn('decision',old['state']);self.assertIsInstance(new['state']['state'],str)
  self.assertIn('Example Strike',str(new));self.assertIn('h0',str(new))
 def test_pending_constraints_survive(self):
  o={'kind':'card_selection','state':{'game':{'enemies':[{'index':0,'creature':{'name':'E','hp':3},'intents':[]}],'hand':[]},'prompt':'Exhaust 1','min':1,'max':1,'source':'Burning Pact'},'actions':[{'id':'a0','option':{'action':'confirm'}}]}
  state,_=build(o,'survive','ironclad','rules')
  for text in ('Exhaust 1','Burning Pact','"min":1','"max":1'):self.assertIn(text,state['state'])
 def test_shop_replay_ignores_only_decorative_text(self):
  from jev_playtest import replay_fingerprint
  o={'kind':'shop','state':{'text':'animated price','game':{'gold':100}},'actions':[{'id':'a0','option':{'action':'purchase','cost':20}}]}
  changed=copy.deepcopy(o);changed['state']['text']='animation frame 2'
  self.assertEqual(replay_fingerprint(o),replay_fingerprint(changed))
  changed['actions'][0]['option']['cost']=21
  self.assertNotEqual(replay_fingerprint(o),replay_fingerprint(changed))
