import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from replay_controls import ReplayControls,ReplaySeek,atomic_json

class ReplayControlTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name);self.controls=ReplayControls(self.path)
 def send(self,action,**extra):atomic_json(self.path/'command.json',dict(nonce=action,action=action,**extra))
 def test_single_step_consumed_once(self):
  self.send('step');self.controls.wait(2,10,{})
  self.assertFalse(self.controls.step);self.assertFalse(self.controls.playing)
  self.controls.command(3);self.assertFalse(self.controls.step)
 def test_back_requests_previous_boundary(self):
  self.send('back')
  with self.assertRaises(ReplaySeek) as caught:self.controls.wait(7,10,{})
  self.assertEqual(caught.exception.args[0],6)
  self.assertFalse((self.path/'restart.json').exists())
 def test_back_during_reconstruction_uses_destination(self):
  self.controls.target=157
  self.send('back');self.controls.wait(14,190,{})
  self.assertEqual(self.controls.target,156)
  import json
  status=json.loads((self.path/'status.json').read_text())
  self.assertEqual(status['index'],156);self.assertEqual(status['reconstruction_index'],14)
 def test_pause_during_reconstruction_does_not_cancel_destination(self):
  self.controls.target=157
  self.send('pause');self.controls.wait(14,190,{})
  self.assertEqual(self.controls.target,157)
 def test_forward_seek_keeps_process(self):
  self.send('seek',index=9);self.controls.wait(3,12,{})
  self.assertEqual(self.controls.target,9)
  self.assertFalse((self.path/'restart.json').exists())
 def test_rate_and_pause(self):
  self.send('rate',seconds=.25);self.controls.command(1);self.assertEqual(self.controls.delay,.25)
  self.send('play');self.controls.command(1);self.assertTrue(self.controls.playing)
  self.send('pause');self.controls.command(1);self.assertFalse(self.controls.playing)
 def test_seek_fast_forward_does_not_call_model_or_wait(self):
  self.controls.target=10;self.controls.wait(0,20,{})
  self.assertFalse(self.controls.playing)

if __name__=='__main__':unittest.main()
