import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from strategy_registry import route_summary

def n(row,col,type_,*kids):return {'row':row,'col':col,'type':type_,'children':[{'row':r,'col':c} for r,c in kids]}

class RouteSummary(unittest.TestCase):
    def test_counts_elites_rests_and_nearest_elite(self):
        # a0 -> Elite -> Boss ; a1 -> Rest -> Monster -> Boss
        state={'map':[n(1,0,'Monster',(2,0)),n(2,0,'Elite',(3,0)),n(1,1,'Monster',(2,1)),n(2,1,'RestSite',(3,0)),n(3,0,'Boss')]}
        obs={'kind':'map','state':state,'actions':[{'id':'a0','option':{'action':'map','row':1,'col':0,'type':'Monster'}},{'id':'a1','option':{'action':'map','row':1,'col':1,'type':'Monster'}}]}
        lines=route_summary(obs).splitlines()
        self.assertIn('a0 Monster: 1-1 Elites',lines[0]);self.assertIn('next Elite 1 rooms later',lines[0])
        self.assertIn('a1 Monster: 0-0 Elites',lines[1]);self.assertIn('up to 1 rest sites',lines[1]);self.assertIn('none ahead',lines[1])
    def test_no_map_is_empty(self):
        self.assertEqual(route_summary({'kind':'map','state':{},'actions':[]}),'')

if __name__=='__main__':unittest.main()
