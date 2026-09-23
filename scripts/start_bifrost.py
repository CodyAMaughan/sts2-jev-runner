#!/usr/bin/env python3
"""Start the local-only evaluation gateway. Never print or copy credential values."""
import argparse,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
IMAGE='maximhq/bifrost@sha256:a8942692af7b4b89196cd8fc33653b7353488dfd58b24078fe793b8574a8084b'
def read_keys(path):
    values={}
    for line in path.read_text().splitlines():
        name,sep,value=line.strip().removeprefix('export ').partition('=')
        if sep and name.strip() in ('GEMINI_API_KEY','OPENAI_API_KEY'):
            value=value.strip()
            if value[:1] in ('"',"'") and value[-1:]==value[:1]:value=value[1:-1]
            else:value=value.split(' #',1)[0].strip()
            values[name.strip()]=value
    return values
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--credentials',type=Path,required=True);a=ap.parse_args()
    keys=read_keys(a.credentials)
    if not all(keys.get(k) for k in ('GEMINI_API_KEY','OPENAI_API_KEY')):raise SystemExit('Expected Gemini and OpenAI keys in the supplied local file')
    env=os.environ.copy();env.update(keys)
    cmd=['docker','create','--name','spire-bifrost','--label','project=spire-playtest','-p','127.0.0.1:18767:8080','-e','GEMINI_API_KEY','-e','OPENAI_API_KEY','-e','LOG_LEVEL=warn',IMAGE]
    subprocess.run(cmd,env=env,check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['docker','cp',str(ROOT/'infra/bifrost/config.json'),'spire-bifrost:/app/data/config.json'],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['docker','start','spire-bifrost'],check=True,stdout=subprocess.DEVNULL,timeout=60)
    print('Bifrost started on http://127.0.0.1:18767 (keys inherited by name, not stored in project config).')
