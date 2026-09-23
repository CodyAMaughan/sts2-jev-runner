import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from decision_models import BifrostModel,JevModel,InvalidDecision,validate
PAYLOAD={'model':'provider/model','state':{'decision':{'kind':'combat'}},'questions':{'action':{'instructions':'survive','criteria':{'a0':'{"action":"end_turn"}'}}}}
class Models(unittest.TestCase):
 def fake(self,contents):
  self.calls=[]
  def transport(url,key,wire,**kw):
   self.calls.append(wire)
   return {'choices':[{'message':{'content':contents.pop(0)}}],'usage':{'prompt_tokens':100,'completion_tokens':10}}
  return BifrostModel(transport,'http://localhost:8080/v1')
 def test_valid_json(self):
  chosen,response,meta=self.fake(['{"action_id":"a0"}']).decide(PAYLOAD)
  self.assertEqual(chosen,'a0');self.assertEqual(response['usage']['input_tokens'],100);self.assertIsNone(meta['cost_usd'])
 def test_repair_accounts_for_both_calls(self):
  chosen,response,meta=self.fake(['not JSON','{"action_id":"a0"}']).decide(PAYLOAD)
  self.assertEqual(len(meta['attempts']),2);self.assertEqual(response['usage']['input_tokens'],200);self.assertEqual(len(self.calls[1]['messages']),4)
 def test_invalid_after_repair_never_returns_action(self):
  with self.assertRaises(InvalidDecision) as caught:self.fake(['{"action_id":"a99"}','{}']).decide(PAYLOAD)
  self.assertEqual(len(caught.exception.attempts),2)
 def test_extra_actions_rejected(self):
  with self.assertRaises(ValueError):validate({'action_id':'a0','then':'a1'},['a0'])
 def test_jev_keeps_typed_choice(self):
  adapter=JevModel(lambda *args:{'answers':{'action':{'type':'choice','choice':'a0'}},'usage':{'input_tokens':100}},'test')
  self.assertAlmostEqual(adapter.decide(PAYLOAD)[2]['cost_usd'],.0000042)

class CliTransports(unittest.TestCase):
 def test_codex_schema_file_and_usage(self):
  from decision_models import CliModel
  import subprocess
  def run(command,**kw):
   self.assertEqual(command[:2],['codex','exec']);self.assertIn('--ignore-user-config',command)
   self.assertNotIn('DEALMAKER_BRIDGE_TOKEN',kw['env'])
   Path(command[command.index('--output-last-message')+1]).write_text('{"action_id":"a0"}')
   return subprocess.CompletedProcess(command,0,stdout=json.dumps({'type':'turn.completed','usage':{'input_tokens':42,'output_tokens':3}}))
  chosen,response,meta=CliModel('codex',runner=run).decide(PAYLOAD)
  self.assertEqual(chosen,'a0');self.assertEqual(response['usage']['input_tokens'],42);self.assertIsNone(meta['cost_usd'])
 def test_claude_structured_output(self):
  from decision_models import CliModel
  import subprocess
  def run(command,**kw):
   self.assertEqual(command[command.index('--tools')+1],'')
   return subprocess.CompletedProcess(command,0,stdout=json.dumps({'structured_output':{'action_id':'a0'},'usage':{'input_tokens':30,'output_tokens':2}}))
  self.assertEqual(CliModel('claude',runner=run).decide(PAYLOAD)[0],'a0')
