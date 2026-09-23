#!/usr/bin/env python3
"""Land on a recorded move INSTANTLY (via SnapshotResume: inject the captured
state straight into a fresh game, no replaying every earlier decision to get
there) and then continue watching the real recorded actions play out with
real animation from that exact point — the "Back is slow" fix for
watch_replay_live.py, which can only reach a position by re-simulating from
the seed.

The trade-off: this needs a snapshot for the target decision (captured by
default on any live/mock Jev run; --no-snapshots opts out), and "seeking" to
a DIFFERENT position than where this process landed still means relaunching
— there's no in-process rewind, because nothing can run a game engine
backward. Landing on a new position is still an instant injection, though,
never a from-the-seed replay.
"""
import argparse, json, secrets, subprocess, sys, time
from pathlib import Path
from replay_controls import atomic_json

ROOT = Path(__file__).resolve().parent.parent
REPLAYS = ROOT / 'docs/playtests/replays'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--at', type=int, default=1, help='Decision number to land on (1-based)')
    display = p.add_mutually_exclusive_group()
    display.add_argument('--headed', action='store_true')
    display.add_argument('--headless', action='store_true')
    args = p.parse_args()
    source = args.run.resolve()
    manifest = json.loads((source / 'manifest.json').read_text())
    decisions = [json.loads(l) for l in (source / 'jev-decisions.jsonl').read_text().splitlines()
                 if json.loads(l).get('kind') == 'decision']
    if not decisions:
        p.error('Recorded run has no decisions to replay')
    if not 1 <= args.at <= len(decisions):
        p.error(f'Decision outside recorded run (1-{len(decisions)})')
    target = decisions[args.at - 1]
    snapshot = source / 'snapshots' / f"{target['decision_id']}.json.gz"
    if not snapshot.is_file():
        p.error(f'No snapshot captured for decision {target["decision_id"]} ({snapshot}); '
                'this run may predate snapshot capture, or used --no-snapshots. '
                'Use the "Instant jump" / "Real playback" modes instead.')

    session = REPLAYS / (source.name + '-resume-' + str(time.time_ns()))
    session.mkdir(parents=True)
    atomic_json(session / 'session.json', dict(source=str(source), mechanism='snapshot_resume', images_or_video=False))
    atomic_json(session / 'status.json', dict(index=args.at - 1, total=len(decisions), mode='Loading', seconds=1, reconstruction_index=None))

    run_id = 'replay-' + session.name
    cmd = [sys.executable, str(ROOT / 'scripts/run_jev.py'),
           '--id', run_id, '--seed', manifest['seed'], '--character', manifest.get('character', 'dealmaker'),
           '--replay', str(source / 'jev-decisions.jsonl'), '--snapshot-resume', str(snapshot),
           '--replay-controls', str(session), '--seek-index', str(args.at - 1),
           '--headed' if args.headed else '--headless',
           '--max-decisions', '100000', '--timeout', '14400']
    print('Snapshot-resume replay: landing on move', args.at, 'instantly, then real playback from there:', session, flush=True)
    try:
        subprocess.run(cmd, cwd=ROOT, check=True)
        status = json.loads((session / 'status.json').read_text())
        if status.get('mode') not in ('Stopped', 'Finished', 'Failed'):
            status.update(mode='Failed', error='Replay process ended unexpectedly')
            atomic_json(session / 'status.json', status)
        if status.get('mode') == 'Failed':
            raise RuntimeError('Snapshot-resume replay failed; inspect ' + str(ROOT / 'docs/playtests/runs' / run_id))
    except Exception as error:
        status = json.loads((session / 'status.json').read_text())
        status.update(mode='Failed', error=str(error))
        atomic_json(session / 'status.json', status)
        raise


if __name__ == '__main__':
    main()
