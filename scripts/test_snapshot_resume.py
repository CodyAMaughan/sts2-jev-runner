#!/usr/bin/env python3
"""One-off verification harness for SnapshotResume.cs: inject a captured
snapshot into the live engine, hand control to the real decision loop, and
watch what happens — specifically whether the run continues naturally into
the NEXT room after the injected combat ends, since that's unverified by the
C# build alone. Not a permanent CLI feature; scripts/run_jev.py has no
--snapshot-resume flag yet on purpose, this is purely to answer that question
before deciding whether to build the real thing.

Reuses run_playtest.py's isolated-profile/DLL-install machinery, matching how
run_jev.py already does it for other modes, just with DEALMAKER_SNAPSHOT_RESUME
set instead of a normal fresh launch.
"""
import argparse, json, os, secrets, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from jev_playtest import request

root = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--id', required=True)
    p.add_argument('--snapshot', required=True, type=Path, help='Path to a captured <n>.json.gz snapshot')
    p.add_argument('--character', required=True)
    p.add_argument('--seed', required=True)
    p.add_argument('--max-decisions', type=int, default=20)
    p.add_argument('--headed', action='store_true')
    a = p.parse_args()

    port = 18765
    token = secrets.token_hex(24)
    env = os.environ.copy()
    env.update(DEALMAKER_REMOTE='1', DEALMAKER_BRIDGE_PORT=str(port), DEALMAKER_BRIDGE_TOKEN=token,
               DEALMAKER_CHARACTER=a.character, DEALMAKER_SNAPSHOT_RESUME=str(a.snapshot.resolve()))
    env.pop('DEALMAKER_SNAPSHOT_CAPTURE', None)  # this is a resume test, not a new recording

    game = subprocess.Popen([sys.executable, str(root / 'scripts/run_playtest.py'), '--id', a.id,
                              '--seed', a.seed, '--policy', 'balanced', '--timeout', '120',
                              '--headed' if a.headed else '--headless'], cwd=root, env=env)
    artifact = root / 'docs/playtests/runs' / a.id
    print('Waiting for game launcher to initialize...', flush=True)
    deadline = time.monotonic() + 20
    while not (artifact / 'manifest.json').is_file():
        if game.poll() is not None:
            raise SystemExit('Game launcher exited before starting: check its own logs')
        if time.monotonic() > deadline:
            raise SystemExit('Game launcher did not initialize in time')
        time.sleep(.2)
    print('Launcher up. Polling bridge for the injected decision...', flush=True)

    log = []
    try:
        deadline = time.monotonic() + 60
        obs = None
        while time.monotonic() < deadline:
            try:
                obs = request(f'http://127.0.0.1:{port}/state', token, timeout=5, retries=1)
            except Exception as e:
                time.sleep(.5); continue
            if obs.get('status') in ('decision', 'stopped', 'terminal'):
                break
            time.sleep(.3)
        if obs is None or obs.get('status') != 'decision':
            print('FAILED: never reached a decision. Last observed status:', obs, flush=True)
            return
        print(f'SUCCESS: injected snapshot produced a live decision — kind={obs["kind"]}, floor={obs["state"].get("floor") or (obs["state"].get("game") or {}).get("floor")}', flush=True)

        from jev_playtest import mock_choice
        def aggressive_choice(obs):
            # mock_choice takes the FIRST play_card option regardless of
            # whether it damages anything, which can stall a fight for a long
            # time. This is only a test harness pacing concern, not part of
            # SnapshotResume itself: prefer any attack that targets an enemy,
            # so verification actually reaches the end of the fight quickly.
            for a in obs['actions']:
                o = a['option']
                if o.get('action') == 'play_card' and o.get('card', {}).get('type') == 'Attack' and o.get('target'):
                    return a['id']
            return mock_choice(obs)
        seen_kinds = []
        for i in range(a.max_decisions):
            kind = obs['kind']
            floor = obs['state'].get('floor') or (obs['state'].get('game') or obs['state']).get('floor')
            seen_kinds.append(kind)
            print(f'  [{i+1}] kind={kind} floor={floor}', flush=True)
            chosen = aggressive_choice(obs)
            ack = request(f'http://127.0.0.1:{port}/action', token, {'decision_id': obs['decision_id'], 'action_id': chosen}, retries=1)
            if not ack.get('accepted'):
                print('FAILED: action rejected:', ack, flush=True); break
            deadline = time.monotonic() + 30
            obs = None
            while time.monotonic() < deadline:
                try:
                    obs = request(f'http://127.0.0.1:{port}/state', token, timeout=5, retries=1)
                except Exception:
                    time.sleep(.3); continue
                if obs.get('status') != 'busy':
                    break
                time.sleep(.2)
            if obs is None or obs.get('status') not in ('decision',):
                print(f'  Run ended/stopped after {i+1} actions: {obs}', flush=True); break

        combat_kinds = {k for k in seen_kinds if k == 'combat'}
        non_combat_kinds = {k for k in seen_kinds if k != 'combat'}
        print()
        print('KINDS SEEN:', seen_kinds)
        if non_combat_kinds:
            print(f'CONTINUATION CONFIRMED: reached non-combat kind(s) {non_combat_kinds} after the injected combat ended — the run continues naturally past the resumed point.')
        elif len(combat_kinds) and len(seen_kinds) < a.max_decisions:
            print('Combat never ended within the decision budget, or the run stopped mid-combat — inconclusive on continuation past this fight.')
        else:
            print('INCONCLUSIVE: never left combat within the decision budget.')
    finally:
        if game.poll() is None:
            game.terminate()
            try: game.wait(timeout=15)
            except subprocess.TimeoutExpired: game.kill()


if __name__ == '__main__':
    main()
