import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from replay_environment import isolate_mods,restore_mods
class ReplayEnvironment(unittest.TestCase):
 def test_extra_mod_excluded_and_restored(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);mods=root/'mods';mods.mkdir();source=root/'source';source.mkdir();names=['BaseLib','Dealmaker','OvernightHarness']
   (source/'game.log').write_text('\n'.join('Found mod manifest file /test/mods/'+n+'/'+n+'.json' for n in names))
   for n in names+['HarryPotter']:(mods/n).mkdir();(mods/n/'data').write_text(n)
   isolate_mods(mods,source,root/'stash');self.assertFalse((mods/'HarryPotter').exists());self.assertTrue((mods/'Dealmaker').exists())
   restore_mods(mods,root/'stash');self.assertEqual((mods/'HarryPotter/data').read_text(),'HarryPotter')
 def test_missing_inventory_fails_before_mutation(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'game.log').write_text('');(root/'mods').mkdir()
   with self.assertRaises(ValueError):isolate_mods(root/'mods',root,root/'stash')
   self.assertFalse((root/'stash').exists())
