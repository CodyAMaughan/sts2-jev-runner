"""Keep later additions to the shared test runner out of historical replays."""
import re,shutil
from pathlib import Path

def recorded_mods(source):
    names=set(re.findall(r'Found mod manifest file .*?/mods/([^/\n]+)/[^/\n]+\.json', (Path(source)/'game.log').read_text()))
    if not {'BaseLib','Dealmaker','OvernightHarness'} <= names:
        raise ValueError('Recorded mod inventory is missing; cannot safely reconstruct replay')
    return names

def isolate_mods(mods,source,stash):
    mods,stash=Path(mods),Path(stash)
    allowed=recorded_mods(source)
    missing=allowed-{p.name for p in mods.iterdir() if p.is_dir()}
    if missing:raise ValueError('Missing recorded mods: '+', '.join(sorted(missing)))
    stash.mkdir(parents=True)
    for p in mods.iterdir():
        if p.is_dir() and p.name not in allowed:shutil.move(p,stash/p.name)

def restore_mods(mods,stash):
    stash=Path(stash)
    if stash.exists():
        for p in stash.iterdir():shutil.move(p,Path(mods)/p.name)
        stash.rmdir()
