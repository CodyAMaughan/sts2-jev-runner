import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from review_run import review
class RoomReviewTests(unittest.TestCase):
 def test_room_usage_and_hp_loss_exclude_healing(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);rows=[]
   for i,hp in enumerate((80,75,75)):
    rows.append({'kind':'decision','decision_id':str(i),'action_id':'a0','request':None,'response':{'usage':{'input_tokens':100,'output_tokens':5}} if i<2 else None,'observation':{'kind':'combat','state':{'act':1,'floor':1,'room':'Monster','turn':i+1,'player':{'hp':hp},'enemies':[]},'actions':[{'id':'a0','option':{'action':'end_turn'}}]}})
   (p/'jev-decisions.jsonl').write_text('\n'.join(map(json.dumps,rows)))
   (p/'decisions.jsonl').write_text(json.dumps({'kind':'combat_end','data':{'act':1,'floor':1,'player':{'hp':81}}}))
   (p/'result.json').write_text(json.dumps({'outcome':'act1_victory'}))
   r=review(p);self.assertEqual(r['model_calls'],2);self.assertEqual(r['total_input_tokens'],200);self.assertAlmostEqual(r['estimated_cost_usd'],200*.042/1e6)
   room=r['rooms'][0];self.assertEqual(room['observed_hp_loss'],5);self.assertEqual(room['post_combat_hp'],81);self.assertEqual(room['assessment'],'clean_candidate')
