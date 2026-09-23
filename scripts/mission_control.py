#!/usr/bin/env python3
"""Local Mission Control: run evidence, exact Jev requests, launches and replay transport."""
import argparse,json,os,re,secrets,signal,subprocess,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from replay_controls import atomic_json
from datetime import datetime
from strategy_registry import Strategy,catalog

ROOT=Path(__file__).resolve().parent.parent
RUNS=ROOT/'docs/playtests/runs'
REPLAYS=ROOT/'docs/playtests/replays'
CHARACTERS=['dealmaker','ironclad','silent','regent','necrobinder','defect']
STRATEGIES=['balanced','boast','wall','favor','bargain']
TOKEN=secrets.token_hex(24)
LOCK=threading.RLock()
JOBS=[]
CACHE={}

def read_json(path,default=None):
    try:return json.loads(path.read_text())
    except (OSError,json.JSONDecodeError):return default

def run_dir(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('Invalid run ID')
    path=RUNS/name
    if not path.is_dir():raise ValueError('Run not found')
    return path

def records(path):
    if not path.is_file():return []
    stamp=(path.stat().st_mtime_ns,path.stat().st_size)
    with LOCK:
        cached=CACHE.get(str(path))
        if cached and cached[0]==stamp:return cached[1]
    data=[]
    for line in path.read_text().splitlines():
        try:data.append(json.loads(line))
        except json.JSONDecodeError:continue # live writer may have a partial last line
    with LOCK:CACHE[str(path)]=(stamp,data)
    return data

def action_label(option):
    parts=[option.get('action','').replace('_',' '),option.get('card',{}).get('name') or option.get('text') or option.get('type') or '']
    target=option.get('target')
    if target:parts.append('→ '+target.get('name','target'))
    return ' · '.join(str(x) for x in parts if x)

def step_summary(row):
    obs=row['observation'];state=obs['state'];game=state.get('game',state)
    selected=next((a['option'] for a in obs['actions'] if a['id']==row['action_id']),{})
    response=row.get('response') or {};usage=response.get('usage',{});answer=response.get('answers',{}).get('action',{})
    return dict(id=row['decision_id'],kind=obs['kind'],floor=game.get('floor'),act=game.get('act'),room=game.get('room'),enemies=[e['creature']['name'] for e in game.get('enemies') or []],turn=game.get('turn'),
        label=action_label(selected),hp=game.get('player',{}).get('hp'),gold=game.get('gold'),
        source=row.get('source','jev' if response else 'replay'),input_tokens=usage.get('input_tokens',0),
        cost=row.get('cost_usd',usage.get('input_tokens',0)*.042/1_000_000 if response else 0),cost_basis=row.get('cost_basis','estimated Jev input rate' if response else 'no model call'),output_tokens=usage.get('output_tokens',0),confidence=answer.get('confidence'),latency=row.get('latency_seconds'),
        skipped=[a['option'].get('text','') for a in obs['actions'] if a['option'].get('action')=='claim_reward'] if selected.get('action')=='proceed' else [])

def run_summary(path):
    manifest=read_json(path/'manifest.json',{})
    result=read_json(path/'result.json',{})
    log=records(path/'jev-decisions.jsonl');header=next((r for r in log if r.get('kind')=='controller'),{})
    decisions=[r for r in log if r.get('kind')=='decision']
    steps=[step_summary(r) for r in decisions];last=steps[-1] if steps else {}
    elapsed=result.get('elapsed_seconds')
    duration_basis='Run wall time (includes setup, pauses and configured delays)'
    if elapsed is None:
        try:
            timestamps=[datetime.fromisoformat(r['utc'].replace('Z','+00:00')) for r in log if r.get('utc')]
            elapsed=max(0,(max(timestamps)-min(timestamps)).total_seconds()) if timestamps else None
        except (ValueError,TypeError):elapsed=None
        duration_basis='Recorded duration so far; may exclude a current pause'
    packet=read_json(path/'strategy-packet.json')
    return dict(id=path.name,seed=manifest.get('seed'),character=manifest.get('character','dealmaker'),
        strategy=header.get('strategy',manifest.get('policy','')),mode=header.get('mode','heuristic'),
        display=manifest.get('display_mode','headless'),outcome=result.get('outcome','running' if (ROOT/'.tooling/overnight/run.lock').exists() and time.time()-(path/'manifest.json').stat().st_mtime<15000 else 'incomplete'),
        completed=result.get('completed_run',False),floor=last.get('floor'),decisions=len(decisions),model_calls=sum(bool(r.get('response')) for r in decisions),
        input_tokens=sum(s['input_tokens'] for s in steps),output_tokens=sum(s['output_tokens'] for s in steps),
        cost=sum(s['cost'] or 0 for s in steps),unknown_cost_moves=sum(s['cost'] is None for s in steps),started=manifest.get('started_utc',''),elapsed=elapsed,duration_basis=duration_basis,model_seconds=sum(s['latency'] or 0 for s in steps if s['source'] in ('jev','bifrost','codex','claude')),strategy_packet_sha256=packet.get('sha256') if packet else None,
        model=next((r['response'].get('model') for r in reversed(decisions) if r.get('response')),header.get('model')),replayable=bool(decisions),
        skips=sum(bool(s['skipped']) for s in steps),build=manifest.get('build_version'))

def current_replay():
    paths=sorted(REPLAYS.glob('*/status.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not paths:return None
    path=paths[0];state=read_json(path,{})
    meta=read_json(path.parent/'session.json',{})
    state.update(session=path.parent.name,source=Path(meta.get('source','')).name,mechanism=meta.get('mechanism','direct_snapshot'),
                 connected=time.time()-path.stat().st_mtime<8 and state.get('mode') not in ('Stopped','Failed','Finished'),updated=path.stat().st_mtime)
    return state

def spawn(command,kind):
    with LOCK:
        if (ROOT/'.tooling/overnight/run.lock').exists() or any(j['process'].poll() is None for j in JOBS):
            raise ValueError('The isolated game is busy. Close the current replay/game before starting another run.')
        directory=ROOT/'docs/dashboard/jobs';directory.mkdir(parents=True,exist_ok=True)
        name=str(time.time_ns());log=(directory/(name+'.log')).open('w')
        env=os.environ.copy();env.setdefault('BIFROST_BASE_URL','http://127.0.0.1:18767/v1')
        process=subprocess.Popen([sys.executable,*command],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        log.close();JOBS.append(dict(id=name,process=process,kind=kind,log=str(directory/(name+'.log'))))
        return dict(job=name,kind=kind)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,data,content_type='application/json'):
        body=data if isinstance(data,bytes) else json.dumps(data).encode()
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.headers.get('Host')!=self.server.address:return self.send(403,{'error':'Invalid host'})
        path=urlparse(self.path).path
        try:
            if path=='/':return self.send(200,(ROOT/'dashboard/index.html').read_bytes(),'text/html; charset=utf-8')
            if path=='/strategies.js':return self.send(200,(ROOT/'dashboard/strategies.js').read_bytes(),'text/javascript; charset=utf-8')
            if path=='/api/config':return self.send(200,dict(csrf=TOKEN,characters=CHARACTERS,strategies=STRATEGIES,strategy_versions=[s['version'] for s in catalog() if s.get('approval')],backends=['jev','bifrost','codex','claude']))
            if path=='/api/runs':
                rows=[run_summary(p.parent) for p in RUNS.glob('*/manifest.json')]
                return self.send(200,sorted(rows,key=lambda r:r['started'],reverse=True))
            if path=='/api/replay':return self.send(200,current_replay())
            if path=='/api/jobs':return self.send(200,[dict(id=j['id'],kind=j['kind'],running=j['process'].poll() is None,exit_code=j['process'].poll()) for j in JOBS])
            diff=re.fullmatch(r'/api/strategy-diff/(\d+\.\d+\.\d+)/(\d+\.\d+\.\d+)',path)
            if diff:
                from strategy_registry import strategy_diff
                return self.send(200,strategy_diff(diff[1],diff[2]))
            if path=='/api/strategies':return self.send(200,catalog())
            contract_match=re.fullmatch(r'/api/context-contracts(?:/(\d+\.\d+\.\d+))?',path)
            if contract_match:
                from context_contracts import contracts
                return self.send(200,contracts(contract_match[1] or "1.1.0"))
            if path=='/api/model-smokes':return self.send(200,[read_json(p) for p in sorted((ROOT/'docs/playtests/model-smokes').glob('*.json'))])
            if path=='/api/examples':
                return self.send(200,[read_json(p) for p in sorted((ROOT/'docs/playtests/prompt-examples').glob('*.json'))])
            video=re.fullmatch(r'/api/runs/([A-Za-z0-9_-]+)/video',path)
            if video:
                directory=run_dir(video[1]);movie=directory/'game.mp4'
                if read_json(directory/'recording.json',{}).get('status')!='complete' or not movie.is_file():return self.send(404,{'error':'No completed recording'})
                self.send_response(200);self.send_header('Content-Type','video/mp4');self.send_header('Content-Length',str(movie.stat().st_size));self.send_header('Content-Disposition','attachment; filename="'+video[1]+'.mp4"');self.end_headers()
                import shutil
                with movie.open('rb') as source:shutil.copyfileobj(source,self.wfile)
                return
            match=re.fullmatch(r'/api/runs/([A-Za-z0-9_-]+)(?:/decisions/(\d+))?',path)
            if match:
                directory=run_dir(match[1]);rows=records(directory/'jev-decisions.jsonl')
                if match[2]:
                    row=next(r for r in rows if r.get('kind')=='decision' and r['decision_id']==match[2])
                    from jev_playtest import make_request,STRATEGIES as PROMPT_STRATEGIES
                    header=next((r for r in rows if r.get('kind')=='controller'),{})
                    from strategy_registry import version_packet
                    package=Strategy(version_packet(catalog()[0]['version']))
                    prompt,route=package.prompt(row['observation'],header.get('character','dealmaker'))
                    preview=make_request(row['observation'],prompt,header.get('model','jev-latest'),header.get('character','dealmaker'),prompt_format=package.packet.get('prompt_format','decision-v2'))
                    return self.send(200,{**row,'current_template_preview':preview,'current_strategy_preview':route})
                return self.send(200,dict(recording=read_json(directory/'recording.json'),room_review=read_json(directory/'room-review.json'),summary=run_summary(directory),manifest=read_json(directory/'manifest.json'),
                    strategy_packet=read_json(directory/'strategy-packet.json'),controller=next((r for r in rows if r.get('kind')=='controller'),{}),steps=[step_summary(r) for r in rows if r.get('kind')=='decision']))
            return self.send(404,{'error':'Not found'})
        except (ValueError,StopIteration,OSError) as e:return self.send(400,{'error':str(e) or 'Decision not found'})
    def do_POST(self):
        if self.headers.get('Host')!=self.server.address or self.headers.get('Origin')!='http://'+self.server.address or self.headers.get('X-Mission-CSRF')!=TOKEN:
            return self.send(403,{'error':'Same-origin session required'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=8192:raise ValueError('Invalid body size')
            data=json.loads(self.rfile.read(length));path=urlparse(self.path).path
            if path=='/api/launch':
                character=data.get('character','dealmaker');strategy=data.get('strategy','balanced');seed=data.get('seed','')
                if character not in CHARACTERS or strategy not in STRATEGIES:raise ValueError('Invalid character or strategy')
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',seed):raise ValueError('Seed must contain 1–64 letters, digits, underscores or hyphens')
                delay=float(data.get('delay',1))
                if not 0<=delay<=60:raise ValueError('Delay must be 0–60 seconds')
                backend=data.get('backend','jev');model=data.get('model','jev-latest')
                if backend not in ('jev','bifrost','codex','claude'):raise ValueError('Invalid backend')
                if not re.fullmatch(r'[A-Za-z0-9_./:-]{1,128}',model):raise ValueError('Invalid model identifier')
                if data.get('record') and not data.get('headed',False):raise ValueError('Recording requires headed mode')
                version=data.get('strategy_version','1.1.0')
                from strategy_registry import require_approved
                require_approved(version)
                identifier=backend+'-'+character+'-'+str(time.time_ns())
                result=spawn(['scripts/run_jev.py','--backend',backend,'--model',model,'--id',identifier,'--seed',seed,'--character',character,'--strategy',strategy,'--strategy-version',version,*(['--act1-overgrowth'] if data.get('act1_overgrowth') else []),*(['--record'] if data.get('record') else []),'--headed' if data.get('headed',False) else '--headless','--decision-delay',str(delay)],backend)
                return self.send(200,{**result,'run':identifier})
            if path=='/api/replay/launch':
                directory=run_dir(data['run']);at=int(data.get('at',1))
                if not 1<=at<=sum(r.get('kind')=='decision' for r in records(directory/'jev-decisions.jsonl')):raise ValueError('Move outside recorded run')
                mode=data.get('mode','snapshot')
                mechanism={'snapshot':'direct_snapshot','live':'legacy_reconstruction','resume':'snapshot_resume'}.get(mode)
                if mechanism is None:raise ValueError('Invalid replay mode')
                current=current_replay()
                # A running snapshot session can seek in place instantly; a live
                # session's "seek" is itself a reset-and-refastforward, so route it
                # through the same in-place command rather than spawning a second one.
                # A resume session can't seek in place at all — landing anywhere new
                # is itself a fresh injection, so every launch spawns its own process.
                if mode!='resume' and current and current['connected'] and current['source']==directory.name and current.get('mechanism')==mechanism:
                    atomic_json(REPLAYS/current['session']/'command.json',dict(action='seek',index=at-1,nonce=secrets.token_hex(12)))
                    return self.send(200,{'accepted':True,'seeking':True})
                script={'snapshot':'scripts/watch_replay.py','live':'scripts/watch_replay_live.py','resume':'scripts/watch_replay_resume.py'}[mode]
                return self.send(200,spawn([script,str(directory),'--at',str(at),'--headed' if data.get('headed',False) else '--headless'],'replay'))
            if path=='/api/replay/control':
                replay=current_replay()
                if not replay or not replay['connected']:raise ValueError('No connected replay. Launch one from a recorded run.')
                action=data.get('action');command=dict(action=action,nonce=secrets.token_hex(12))
                if action not in ('back','step','play','pause','rate','seek','stop'):raise ValueError('Invalid replay action')
                # A resume session was launched by injecting one specific snapshot;
                # there's no in-process reset path back to a different position (that
                # only exists for the seed-replay mechanism). Landing somewhere else
                # means relaunching via /api/replay/launch, not seeking in place.
                if action in ('back','seek') and replay.get('mechanism')=='snapshot_resume':raise ValueError('A resumed session can\'t seek to a different move in place — use "Load selected move" with the new target instead')
                if action=='rate':
                    seconds=float(data.get('seconds',1))
                    if not 0<=seconds<=60:raise ValueError('Invalid delay')
                    command['seconds']=seconds
                if action=='seek':
                    index=int(data['index'])
                    if not 0<=index<replay['total']:raise ValueError('Move outside run')
                    command['index']=index
                atomic_json(REPLAYS/replay['session']/'command.json',command)
                return self.send(200,{'accepted':True,'command':command['nonce']})
            return self.send(404,{'error':'Not found'})
        except (ValueError,KeyError,OSError) as e:return self.send(400,{'error':str(e)})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18766);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.address='127.0.0.1:'+str(args.port)
    print('Mission Control: http://'+server.address,flush=True);server.serve_forever()

if __name__=='__main__':main()
