"""Small factual history for a stateless pilot; never chooses or hides actions."""
import copy

class DecisionMemory:
    def __init__(self, planning=False):
        self.planning = planning
        self.seen_elites = set()
        self.act = None
        self.room = None
        self.declined = []

    def enrich(self, obs):
        game = obs['state'].get('game', obs['state'])
        room = (game.get('act'), game.get('floor'))
        if room != self.room:
            self.room, self.declined = room, []
        if self.act != game.get('act'):
            self.act = game.get('act')
            self.seen_elites.clear()
        if self.planning and obs['kind']=='combat' and game.get('room')=='Elite':
            self.seen_elites.update(e['creature']['name'] for e in game.get('enemies') or [])
        result = copy.deepcopy(obs)
        if self.planning:
            result['planning_context']=True
            if obs['kind'] in {'card_reward','choose_card','bundle','shop','rest','map','event','upgrade','card_selection','rewards'}:
                plan={k:game[k] for k in ('known_boss','potion_slots_free') if k in game}
                if self.seen_elites:plan['seen_elite_enemies_this_act']=sorted(self.seen_elites)
                if plan:result['run_plan']=plan
        if self.declined and obs['kind'] in {'rewards', 'card_reward'}:
            result['observed_history'] = {'declined_card_offers_this_room': self.declined,
                'meaning': 'These offers were inspected and skipped already. Reopening the same reward does not reroll it. Other rewards may differ.'}
        return result

    def observe(self, obs, chosen):
        self.enrich(obs)  # Also resets when called during prefix reconstruction.
        action = next(a['option'] for a in obs['actions'] if a['id'] == chosen)
        if obs['kind'] == 'card_reward' and action.get('action') in {'skip', 'reward_alternative'} and 'skip' in action.get('text', 'skip').lower():
            offer = [a['option']['card'].get('name', a['option']['card'].get('id'))
                     for a in obs['actions'] if isinstance(a['option'].get('card'), dict)]
            if offer and offer not in self.declined:
                self.declined.append(offer)
