"""Decision-boundary replay controls. Backward seeks reset the run inside the game."""
import json,time
from pathlib import Path

class ReplaySeek(Exception): pass
class ReplayStop(Exception): pass

def atomic_json(path, data):
    path=Path(path);tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data));tmp.replace(path)

class ReplayControls:
    def __init__(self,directory,target=0):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.target=target;self.playing=False;self.delay=1.;self.last_command=None;self.step=False;self.pending_seek=None
    def command(self,index):
        try:cmd=json.loads((self.directory/'command.json').read_text())
        except (OSError,json.JSONDecodeError):return
        if cmd.get('nonce')==self.last_command:return
        self.last_command=cmd.get('nonce');action=cmd.get('action')
        if action=='stop':
            self.status(index,0,'Stopped');raise ReplayStop()
        # Reconstruction is internal: transport commands refer to the requested
        # decision, never an intermediate move near the start of the run.
        rebuilding=index<self.target
        if rebuilding and action in ('play','pause','step'):return
        if action=='play':self.playing=True
        elif action=='pause':self.playing=False;self.target=index
        elif action=='step':self.playing=False;self.step=True;self.target=index
        elif action=='rate':self.delay=max(0,min(60,float(cmd['seconds'])))
        elif action in ('back','seek'):self.pending_seek=max(0,(self.target if rebuilding else index)-1) if action=='back' else max(0,int(cmd['index']))
    def wait(self,index,total,observation):
        started=time.monotonic()
        while True:
            self.command(index)
            if self.pending_seek is not None:
                target=min(total-1,self.pending_seek);self.pending_seek=None
                self.playing=False;self.step=False;self.target=target
                if target<index:raise ReplaySeek(target)
            if index<self.target:self.status(index,total,'Seeking');return
            self.status(index,total,'Playing' if self.playing else 'Paused')
            if self.step:self.step=False;return
            if self.playing and time.monotonic()-started>=self.delay:return
            time.sleep(.1)
    def status(self,index,total,mode):
        rebuilding=mode in ('Seeking','Reconstructing')
        atomic_json(self.directory/'status.json',dict(index=self.target if rebuilding else index,total=total,mode=mode,seconds=self.delay,reconstruction_index=index if rebuilding else None))
