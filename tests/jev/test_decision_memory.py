import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from decision_memory import DecisionMemory

class HistoryTests(unittest.TestCase):
    def offer(self,floor=2):
        return {'kind':'card_reward','state':{'game':{'act':1,'floor':floor}},'actions':[
            {'id':'a0','option':{'action':'select_card','card':{'name':'Anger'}}},
            {'id':'a1','option':{'action':'reward_alternative','text':'Skip'}}]}
    def test_skip_is_fact_not_action_override_and_resets_per_room(self):
        m=DecisionMemory();o=self.offer();m.observe(o,'a1');rewards={'kind':'rewards','state':{'game':{'act':1,'floor':2}},'actions':[]}
        enriched=m.enrich(rewards)
        self.assertEqual(enriched['observed_history']['declined_card_offers_this_room'],[['Anger']])
        self.assertNotIn('observed_history',rewards)
        self.assertEqual(enriched['actions'],rewards['actions'])
        self.assertNotIn('observed_history',m.enrich(self.offer(3)))
    def test_taking_card_does_not_mark_declined(self):
        m=DecisionMemory();o=self.offer();m.observe(o,'a0');self.assertNotIn('observed_history',m.enrich(o))
    def test_new_offer_is_recorded_separately(self):
        m=DecisionMemory();o=self.offer();m.observe(o,'a1');m.observe(o,'a1');o['actions'][0]['option']['card']['name']='Bash';m.observe(o,'a1')
        self.assertEqual(m.enrich(o)['observed_history']['declined_card_offers_this_room'],[['Anger'],['Bash']])

    def test_new_request_puts_strategy_in_instruction_field(self):
        from jev_playtest import make_request
        o={'kind':'rewards','context_policy':'observed-history-v1','state':{'game':{'act':1,'floor':2,'player':{'hp':50,'max_hp':80}}},'actions':[{'id':'a0','option':{'action':'claim_reward','type':'CardReward','text':'Add a card'}}]}
        payload=make_request(o,'Inspect before skipping.','jev-latest','ironclad','decision-v3')
        self.assertIn('Inspect before skipping.',payload['questions']['action']['instructions'])
        self.assertNotIn('strategy',payload['state'])
        self.assertIn('adds no card yet',payload['questions']['action']['criteria']['a0'])
        self.assertEqual(o['actions'][0]['option']['text'],'Add a card')

    def test_planning_uses_public_boss_and_only_observed_elites(self):
        m=DecisionMemory(planning=True)
        o={'kind':'card_reward','state':{'game':{'act':1,'floor':2,'known_boss':'VANTOM_BOSS','potion_slots_free':3}},'actions':[]}
        self.assertEqual(m.enrich(o)['run_plan'],{'known_boss':'VANTOM_BOSS','potion_slots_free':3})
        elite={'kind':'combat','state':{'act':1,'floor':4,'room':'Elite','enemies':[{'creature':{'name':'BYRDONIS'}}]},'actions':[]}
        m.enrich(elite)
        self.assertEqual(m.enrich(o)['run_plan']['seen_elite_enemies_this_act'],['BYRDONIS'])
        o['state']['game']['act']=2
        self.assertNotIn('seen_elite_enemies_this_act',m.enrich(o)['run_plan'])

    def test_slippery_overrides_bash_setup(self):
        from strategy_registry import Strategy,version_packet
        s=Strategy(version_packet('1.1.4'))
        o={'kind':'combat','state':{'room':'Boss','energy':3,'player':{'block':0},'enemies':[{'creature':{'name':'VANTOM','powers':[{'id':'SLIPPERY_POWER','amount':8}]},'intents':[]}], 'hand':[{'card':{'id':'BASH','type':'Attack','cost':2}},{'card':{'id':'STRIKE_IRONCLAD','type':'Attack','cost':1}}]},'actions':[]}
        prompt,selection=s.prompt(o,'ironclad')
        self.assertIn(s.packet['turn_advice']['slippery'],selection['addenda'])
        self.assertNotIn(s.packet['turn_advice']['bash_setup'],selection['addenda'])

    def test_draft_gets_known_boss_advice_only(self):
        from strategy_registry import Strategy,version_packet
        s=Strategy(version_packet('1.1.4'));o=self.offer();o['run_plan']={'known_boss':'VANTOM_BOSS'}
        self.assertIn(s.packet['boss_plans']['VANTOM_BOSS'],s.prompt(o,'ironclad')[0])
        o['run_plan']={};self.assertNotIn(s.packet['boss_plans']['VANTOM_BOSS'],s.prompt(o,'ironclad')[0])
