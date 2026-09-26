#!/usr/bin/env python3
"""Run a list of Jev playtests across N isolated runner slots in parallel.
Slot "" is the original .tooling/overnight clone; slot "2" is .tooling/overnight2, etc.
Each slot has its own game copy, save profile, lock and bridge port."""
import argparse, os, queue, subprocess, sys, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix', required=True); p.add_argument('--seeds', nargs='+', required=True)
    p.add_argument('--first-index', type=int, default=1, help='Number the first run id from this (to extend a batch split across invocations)')
    p.add_argument('--slots', nargs='+', default=['', '2'])
    p.add_argument('--timeout', type=int, default=1500)
    p.add_argument('extra', nargs=argparse.REMAINDER, help='passed through to run_jev.py after --')
    a = p.parse_args()
    extra = a.extra[1:] if a.extra[:1] == ['--'] else a.extra
    work = queue.Queue()
    for i, seed in enumerate(a.seeds, a.first_index): work.put((f'{a.prefix}-{i:02d}', seed))
    lock = threading.Lock()
    def worker(slot, port):
        while True:
            try: run_id, seed = work.get_nowait()
            except queue.Empty: return
            env = os.environ.copy(); env['DEALMAKER_SLOT'] = slot
            cmd = [sys.executable, str(ROOT/'scripts/run_jev.py'), '--id', run_id, '--seed', seed, '--port', str(port),
                   '--timeout', str(a.timeout), '--headless', *extra]
            with lock: print(f'{time.strftime("%H:%M:%S")} START {run_id} {seed} slot={slot or 1}', flush=True)
            log = (ROOT/'docs/playtests/runs'/f'.{run_id}.batch.log')
            with log.open('w') as out: code = subprocess.run(cmd, cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT).returncode
            with lock: print(f'{time.strftime("%H:%M:%S")} END {run_id} exit={code}', flush=True)
    threads = [threading.Thread(target=worker, args=(slot, 18765 + 10*(int(slot or 1)-1))) for slot in a.slots]
    for t in threads: t.start(); time.sleep(3)
    for t in threads: t.join()
    print('BATCH COMPLETE', flush=True)

if __name__ == '__main__': main()
