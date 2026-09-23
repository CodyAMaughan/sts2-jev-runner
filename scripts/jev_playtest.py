#!/usr/bin/env python3
"""Jev decision controller for the isolated, real-engine Dealmaker harness."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error
from playtest_config import typesafe_key

API = 'https://api.typesafe.ai/v1/systemone'
STRATEGIES = {
    'balanced': 'Maximize survival and the chance of winning the run. Build a coherent deck from the offers; do not force an archetype.',
    'boast': 'Explore Strength and Boast scaling. Complete active promises when worthwhile; avoid resetting a nearly completed promise without enough attacks. Still draft defense and support.',
    'wall': 'Explore Wall as persistent defense and its conversion/payoff cards. Avoid excessive defense when enemies need to die. Still draft damage and scaling.',
    'favor': 'Explore retained Favors and their offensive and defensive uses. Compare cash-out payoffs against individual Favor plays and preservation for later turns.',
    'bargain': 'Explore exhaust, Bargain, Spin and debt synergies. Clear IOUs to unlock attacks. Judge whether the exhaust outlet and the payoff support each other; do not force bad picks.',
}
RULES = ('Play Slay the Spire 2 with the Dealmaker mod. Card text in the observation is authoritative. '
         'Boast N stacks a promise, resets its attack counter, and requires two subsequent attacks this turn; '
         'success gives N Strength, failure adds N Embarrassment to the top of the draw pile. '
         'Wall persists; ordinary Block normally expires. Favors retain and offer damage or Block. '
         'IOUs restrict non-Spin attacks while in hand and cost 1 energy to settle. Bargain: once per card per combat, when another card or Power exhausts it from hand during your turn, play it free then leave it exhausted. Self-exhaust and Ethereal do not trigger it. '
         'Use only visible information: draw-pile order and future RNG are unknown. '
         'Choose ONE offered action now, including its target. Re-evaluate after every action. '
         'Do not treat confidence as a probability of winning. Prioritize avoiding preventable lethal damage.')


# Transient failures (network blips, upstream 5xx like Cloudflare's 520/522/524) are
# retried with backoff. Anything else — 4xx, a malformed response — is not: retrying
# a bad request or a rejected key forever just burns time without becoming valid.
RETRYABLE_HTTP_CODES = {500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 528, 529, 530}
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2


def request(url, token, payload=None, timeout=35, retries=RETRY_ATTEMPTS, backoff=RETRY_BACKOFF_SECONDS):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {'Authorization': 'Bearer '+token, 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0 (compatible; Dealmaker-Jev-Controller/1.0)'}
    last_error = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in RETRYABLE_HTTP_CODES or attempt == retries:
                raise
            last_error = error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == retries:
                raise
            last_error = error
        wait = backoff * (2 ** (attempt - 1))
        print(f'request retry {attempt}/{retries - 1} after {type(last_error).__name__}: {last_error} (waiting {wait}s)', flush=True)
        time.sleep(wait)
    raise last_error  # pragma: no cover — loop always returns or raises above


def fingerprint(observation):
    return hashlib.sha256(json.dumps(observation, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def replay_fingerprint(observation):
    # The map's decorative act title fades in asynchronously. It is duplicated
    # by structured act/room/map data and does not change legal decisions.
    # Shop animations likewise change label text; inventory/legal choices and
    # player gold/deck remain strictly fingerprinted.
    state = observation.get('state', {})
    if state.get('screen') == 'NMapScreen' or observation.get('kind')=='shop':
        observation = {**observation, 'state': {k:v for k,v in state.items() if k != 'text'}}
    return fingerprint(observation)


def make_request(obs, strategy, model, character='dealmaker',prompt_format=None):
    options = obs['actions']
    if not 1 <= len(options) <= 255:
        raise ValueError('Decision needs 1–255 options; split larger selections into sequential decisions')
    ids = [a['id'] for a in options]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate action IDs')
    from decision_prompts import build, INSTRUCTIONS, rules_for
    rules = rules_for(obs,character)
    state, actions = build(obs, strategy, character, rules,prompt_format)
    instruction = 'Choose one offered action.' if state.get('format','').startswith('decision-v3') else INSTRUCTIONS.get(obs['kind'], 'Choose the best offered action for the strategy.')
    if obs.get('context_policy') == 'observed-history-v1':
        instruction = state.pop('strategy') + '\nChoose one offered action using the current state.'
    return {'model': model, 'state': state, 'questions': {'action': {
        'type': 'choice', 'instructions': instruction,
        'criteria': {key: value if isinstance(value,str) else json.dumps(value, separators=(',', ':')) for key,value in actions.items()}}}}


def parse_answer(response, obs):
    answer = response['answers']['action']
    if answer.get('type') != 'choice' or answer.get('choice') not in {a['id'] for a in obs['actions']}:
        raise ValueError('Model returned an unoffered action; refusing to act')
    return answer['choice']


def mock_choice(obs):
    """Transport smoke only; deliberately not advertised as Jev or a balance pilot."""
    opts = obs['actions']
    priority = ['confirm_selection','play_card','select_card','claim_reward','take_relic','confirm','event_option','map','rest_option','leave_shop','proceed','skip','end_turn']
    for kind in priority:
        matching = [a for a in opts if a['option'].get('action') == kind]
        if matching:
            return matching[0]['id']
    return opts[0]['id']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', type=int, default=18765)
    ap.add_argument('--strategy', choices=STRATEGIES, default='balanced')
    ap.add_argument('--strategy-file', type=Path)
    ap.add_argument('--model')
    ap.add_argument('--backend', choices=['jev','bifrost','codex','claude'], default='jev')
    ap.add_argument('--character',default='dealmaker',choices=['dealmaker','ironclad','silent','regent','necrobinder','defect','harry'])
    ap.add_argument('--log', type=Path, required=True)
    ap.add_argument('--max-decisions', type=int, default=1000)
    ap.add_argument('--max-seconds', type=int, default=3600)
    ap.add_argument('--mock', action='store_true', help='No API calls: protocol smoke, NOT a Jev playtest')
    ap.add_argument('--replay', type=Path, help='Replay recorded decisions, aborting on observation mismatch')
    ap.add_argument('--replay-controls', type=Path)
    ap.add_argument('--seek-index', type=int, default=0)
    ap.add_argument('--decision-delay', type=float, default=0, help='Seconds to pause before each action')
    args = ap.parse_args()
    if not args.model:
        if args.backend!='jev':ap.error('Specify --model for this backend')
        args.model='jev-latest'
    if not 0 <= args.decision_delay <= 60:
        ap.error('--decision-delay must be between 0 and 60 seconds')
    token = os.environ.get('DEALMAKER_BRIDGE_TOKEN', '')
    if len(token) < 24:
        ap.error('Set DEALMAKER_BRIDGE_TOKEN to the same random token used by the game runner')
    if not args.mock and not args.replay:
        from strategy_registry import require_approved
        require_approved()
    api_key = typesafe_key() if not args.mock and not args.replay and args.backend=='jev' else ''
    if not args.mock and not args.replay and args.backend=='jev' and not api_key:
        ap.error('Set TYPESAFE_API_KEY locally; do not paste it into chat')
    if args.mock and args.replay:
        ap.error('Choose mock or replay, not both')
    from decision_models import JevModel,BifrostModel,CliModel,InvalidDecision
    adapter=None
    if not args.mock and not args.replay:
        if args.backend=='jev':adapter=JevModel(request,api_key)
        elif args.backend=='bifrost':
            if not os.environ.get('BIFROST_BASE_URL'):ap.error('Set BIFROST_BASE_URL including /v1')
            adapter=BifrostModel(request,os.environ['BIFROST_BASE_URL'],os.environ.get('BIFROST_API_KEY',''))
        else:adapter=CliModel(args.backend)
    strategy = args.strategy_file.read_text() if args.strategy_file else STRATEGIES[args.strategy]
    from strategy_registry import Strategy
    strategy_package=Strategy.load(strategy if args.strategy_file or args.strategy!='balanced' else None,args.strategy)
    from decision_memory import DecisionMemory
    memory=DecisionMemory(planning=strategy_package.packet.get('planning_context',False))
    context_policy=strategy_package.packet.get('observation_policy')
    replay_rows = [json.loads(line) for line in args.replay.read_text().splitlines() if json.loads(line).get('kind') == 'decision'] if args.replay else []
    replay = iter(replay_rows) if args.replay else None
    controls = None
    if args.replay_controls:
        if not args.replay: ap.error('--replay-controls requires --replay')
        from replay_controls import ReplayControls
        controls = ReplayControls(args.replay_controls, args.seek_index)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    if not args.replay:strategy_package.save(args.log.parent/'strategy-packet.json')
    start = time.monotonic()
    with args.log.open('x') as log:
        def record(data):
            log.write(json.dumps({'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()), **data})+'\n'); log.flush()
        record({'kind':'controller', 'mode':'replay' if replay else 'mock_transport_test' if args.mock else args.backend, 'backend':args.backend, 'prompt_version':strategy_package.packet.get('prompt_format','decision-v2'), 'model':args.model, 'strategy':strategy, 'character':args.character, 'decision_delay_seconds':args.decision_delay,'planning_context':strategy_package.packet.get('planning_context',False),'strategy_packet_sha256':strategy_package.sha256 if not args.replay else None})
        seen = set()
        count=0
        while count < args.max_decisions:
            while True:
                if time.monotonic()-start > args.max_seconds:
                    record({'kind':'stopped','reason':'time_budget'}); return
                try:
                    obs = request(f'http://127.0.0.1:{args.port}/state', token, timeout=5, retries=1)
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    time.sleep(.2); continue
                if obs.get('status') == 'decision' and obs['decision_id'] not in seen:
                    break
                if obs.get('status') in ('stopped','terminal'):
                    record({'kind':'stopped','state':obs}); return
                time.sleep(.1)
            if os.environ.get('DEALMAKER_ACT1_OVERGROWTH')=='1':
                game=obs['state'].get('game',obs['state'])
                if game.get('act',1)>1:
                    record({'kind':'scope_complete','outcome':'act1_victory','observation':obs});return
                if game.get('act_id')!='OVERGROWTH':
                    raise RuntimeError('Expected Overgrowth; refusing model calls in a different act')
            digest = fingerprint(obs)
            model_obs=memory.enrich(obs) if context_policy else obs
            if context_policy:model_obs['context_policy']=context_policy
            active_strategy,strategy_selection=strategy_package.prompt(model_obs,args.character)
            payload = None
            before = time.monotonic()
            source = args.backend
            model_meta={'cost_usd':0,'cost_basis':'no model call'}
            if replay is not None:
                if count>=len(replay_rows):
                    record({'kind':'replay_trace_complete','decisions':count})
                    return
                previous = replay_rows[count]
                if previous['observation_sha256'] != fingerprint(previous['observation']):
                    raise RuntimeError('Recorded observation hash is invalid')
                if replay_fingerprint(previous['observation']) != replay_fingerprint(obs):
                    raise RuntimeError('Replay diverged; no action submitted')
                if controls:
                    from replay_controls import ReplaySeek
                    try: controls.wait(count, len(replay_rows), obs)
                    except ReplaySeek as seek:
                        ack=request(f'http://127.0.0.1:{args.port}/reset',token,{},retries=1)
                        if not ack.get('accepted'): raise RuntimeError('Game refused in-process replay reset')
                        record({'kind':'replay_seek','from_index':count,'to_index':seek.args[0]})
                        count=0;seen.clear();controls.status(0,len(replay_rows),'Reconstructing')
                        continue
                chosen = previous['action_id']; response = None
                source = 'replay'
            elif args.mock:
                chosen = mock_choice(obs); response = None
                source = 'mock'
            elif len(obs['actions']) == 1:
                chosen = obs['actions'][0]['id']; response = None
                source = 'sole_legal_action'
            else:
                payload = make_request(model_obs, active_strategy, args.model, args.character, strategy_package.packet.get('prompt_format'))
                # A failed request stops this controller. No silent heuristic fallback.
                try:chosen,response,model_meta=adapter.decide(payload)
                except InvalidDecision as error:
                    record({'kind':'model_failure','decision_id':obs['decision_id'],'attempts':error.attempts})
                    raise
            if chosen not in {a['id'] for a in obs['actions']}:
                raise ValueError('Replay selected an unoffered action')
            record({'kind':'decision','decision_id':obs['decision_id'],'observation_sha256':digest,'observation':obs,
                    'request':payload,'response':response,'action_id':chosen,'source':source,'strategy_selection':strategy_selection if not args.replay else previous.get('strategy_selection'),'latency_seconds':time.monotonic()-before,**model_meta})
            if args.decision_delay:
                time.sleep(args.decision_delay)
            ack = request(f'http://127.0.0.1:{args.port}/action',token,{'decision_id':obs['decision_id'],'action_id':chosen},retries=1)
            if not ack.get('accepted'):
                raise RuntimeError('Game rejected action')
            memory.observe(obs,chosen)
            seen.add(obs['decision_id'])
            print(f"{count+1}: {obs['kind']} {chosen}", flush=True)
            count+=1
        record({'kind':'stopped','reason':'decision_budget','decisions':args.max_decisions})

if __name__ == '__main__':
    from replay_controls import ReplaySeek, ReplayStop
    try: main()
    except ReplaySeek: raise SystemExit(75)
    except ReplayStop: raise SystemExit(0)
