import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import watch_replay
from prepare_snapshot_replay import publish_index
class SnapshotIndex(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.source=self.root/'docs/playtests/runs/source';self.source.mkdir(parents=True)
  self.trace=self.source/'jev-decisions.jsonl';self.trace.write_text('{"kind":"decision","decision_id":"1"}\n')
  self.directory=self.root/'docs/playtests/runs/conversion/snapshots';self.directory.mkdir(parents=True);(self.directory/'1.json.gz').write_bytes(b'fixture')
  self.index=dict(mechanism='direct_snapshot',trace_sha256=hashlib.sha256(self.trace.read_bytes()).hexdigest(),directory=str(self.directory),count=1)
  (self.source/'snapshot-index.json').write_text(json.dumps(self.index))
 def load(self):
  with patch.object(watch_replay,'ROOT',self.root):return watch_replay.snapshot_index(self.source)
 def test_direct_snapshot_index(self):self.assertEqual(self.load()['mechanism'],'direct_snapshot')
 def test_changed_trace_rejected(self):
  self.trace.write_text('different')
  with self.assertRaisesRegex(ValueError,'does not match'):self.load()
 def test_missing_position_rejected(self):
  (self.directory/'1.json.gz').unlink()
  with self.assertRaisesRegex(ValueError,'missing'):self.load()
 def test_directory_escape_rejected(self):
  self.index['directory']=str(self.root/'elsewhere');(self.source/'snapshot-index.json').write_text(json.dumps(self.index))
  with self.assertRaisesRegex(ValueError,'outside'):self.load()
 def test_publish_requires_every_recorded_decision_verified(self):
  (self.source/'snapshot-index.json').unlink()
  (self.directory.parent/'decisions.jsonl').write_text('')
  with self.assertRaisesRegex(RuntimeError,'incomplete'):publish_index(self.source,self.directory.parent)
  self.assertFalse((self.source/'snapshot-index.json').exists())
 def test_publish_preserves_trace_and_indexes_verified_capture(self):
  original=self.trace.read_bytes()
  (self.directory.parent/'decisions.jsonl').write_text('{"kind":"snapshot_verified","data":{"id":"1"}}\n')
  result=publish_index(self.source,self.directory.parent)
  self.assertEqual(result['count'],1)
  self.assertEqual(result['model_calls'],0)
  self.assertEqual(self.trace.read_bytes(),original)
