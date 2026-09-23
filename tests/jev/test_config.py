import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from playtest_config import typesafe_key,display_args

class ConfigTests(unittest.TestCase):
 def test_modes(self):
  self.assertEqual(display_args(False),['--headless'])
  self.assertNotIn('--headless',display_args(True))
  self.assertIn('--windowed',display_args(True))
 def test_file_literal_and_environment_precedence(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'.env.local';p.write_text('# test only\nTYPESAFE_API_KEY="literal-$(not-executed)"\n')
   with patch.dict(os.environ,{'TYPESAFE_API_KEY':''}):self.assertEqual(typesafe_key(p),'literal-$(not-executed)')
   with patch.dict(os.environ,{'TYPESAFE_API_KEY':'environment-value'}):self.assertEqual(typesafe_key(p),'environment-value')
