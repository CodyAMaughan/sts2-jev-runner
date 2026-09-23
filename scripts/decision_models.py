"""Interchangeable decision transports. All consume the same projected facts/actions.
No adapter can execute a game action. Invalid output gets at most one repair;
all attempts remain in the returned record for latency/usage accounting.
"""
from abc import ABC,abstractmethod
import json,os,subprocess,tempfile,time
from pathlib import Path

SCHEMA_BASE={'type':'object','properties':{'action_id':{'type':'string'}},'required':['action_id'],'additionalProperties':False}

class InvalidDecision(ValueError):
    def __init__(self,attempts):
        super().__init__('Model failed to return a legal action after bounded repair')
        self.attempts=attempts

def schema(ids):
    return {**SCHEMA_BASE,'properties':{'action_id':{'type':'string','enum':list(ids)}}}

def validate(value,ids):
    if isinstance(value,str):value=json.loads(value)
    if not isinstance(value,dict) or set(value)!={'action_id'} or value['action_id'] not in ids:
        raise ValueError('Expected only action_id containing an offered ID')
    return value['action_id']

class DecisionModel(ABC):
    @abstractmethod
    def decide(self,payload):pass

class JevModel(DecisionModel):
    def __init__(self,transport,key):self.transport=transport;self.key=key
    def decide(self,payload):
        response=self.transport('https://api.typesafe.ai/v1/systemone',self.key,payload)
        answer=response.get('answers',{}).get('action',{})
        if answer.get('type')!='choice' or answer.get('choice') not in payload['questions']['action']['criteria']:
            raise InvalidDecision([{'request':payload,'response':response}])
        tokens=response.get('usage',{}).get('input_tokens')
        return answer['choice'],response,{'cost_usd':None if tokens is None else tokens*.042/1e6,'cost_basis':'estimated Jev input rate: $0.042/M; not an invoice'}

class JsonDecisionModel(DecisionModel):
    @abstractmethod
    def complete(self,messages,output_schema,model):pass
    def decide(self,payload):
        ids=payload['questions']['action']['criteria'];attempts=[]
        common={'state':payload['state'],'instruction':payload['questions']['action']['instructions'],
                'actions':{k:json.loads(v) for k,v in ids.items()}}
        messages=[{'role':'system','content':'You choose a Slay the Spire action using only supplied facts. No tools. Return only JSON {"action_id":"an offered ID"}.'},
                  {'role':'user','content':json.dumps(common,separators=(',',':'))}]
        for number in range(2):
            started=time.monotonic()
            content,raw,usage,wire=self.complete(messages,schema(ids),payload['model'])
            attempts.append({'request':wire,'response':raw,'usage':usage,'latency_seconds':time.monotonic()-started})
            try:chosen=validate(content,ids)
            except (ValueError,TypeError):
                if number==1:raise InvalidDecision(attempts)
                messages=messages+[{'role':'assistant','content':content if isinstance(content,str) else json.dumps(content)},
                    {'role':'user','content':'Invalid output. Return exactly one JSON object with only action_id, chosen from: '+','.join(ids)}]
                continue
            totals={k:sum(a['usage'].get(k,0) for a in attempts) for k in ('input_tokens','output_tokens','cached_input_tokens')}
            response={'model':raw.get('model',payload['model']),'answers':{'action':{'type':'choice','choice':chosen}},'usage':totals}
            return chosen,response,{'attempts':attempts,'cost_usd':None,'cost_basis':'unavailable; configure provider pricing or read gateway billing','provider':type(self).__name__}

class BifrostModel(JsonDecisionModel):
    def __init__(self,transport,url,key=''):self.transport=transport;self.url=url.rstrip('/')+'/chat/completions';self.key=key
    def complete(self,messages,output_schema,model):
        wire={'model':model,'messages':messages,'response_format':{'type':'json_schema','json_schema':{'name':'decision','strict':True,'schema':output_schema}}}
        raw=self.transport(self.url,self.key,wire,timeout=120)
        usage=raw.get('usage',{})
        return raw['choices'][0]['message']['content'],raw,{'input_tokens':usage.get('prompt_tokens',0),'output_tokens':usage.get('completion_tokens',0),'cached_input_tokens':usage.get('prompt_tokens_details',{}).get('cached_tokens',0)},wire

class CliModel(JsonDecisionModel):
    """Use official installed CLIs and their own login. Never read OAuth stores.
    CLI tool overhead differs from direct API calls and must be reported separately.
    """
    def __init__(self,provider,runner=subprocess.run):
        if provider not in ('codex','claude'):raise ValueError('Unsupported CLI')
        self.provider=provider;self.runner=runner
    def complete(self,messages,output_schema,model):
        prompt='\n'.join(m['role']+': '+m['content'] for m in messages)
        with tempfile.TemporaryDirectory(prefix='spire-decision-') as directory:
            root=Path(directory);schema_file=root/'schema.json';schema_file.write_text(json.dumps(output_schema))
            output=root/'answer.json'
            if self.provider=='codex':
                command=['codex','exec','--ignore-user-config','--ephemeral','--skip-git-repo-check','--sandbox','read-only','-c','approval_policy="never"','-c','features.shell_tool=false','--json','--output-schema',str(schema_file),'--output-last-message',str(output),'-m',model,'-']
            else:
                command=['claude','-p','--output-format','json','--json-schema',json.dumps(output_schema),'--tools','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--disable-slash-commands','--setting-sources','','--no-session-persistence','--model',model]
            if model=='default':
                flag='-m' if self.provider=='codex' else '--model';position=command.index(flag);del command[position:position+2]
            env={k:v for k,v in os.environ.items() if k not in ('TYPESAFE_API_KEY','DEALMAKER_BRIDGE_TOKEN','BIFROST_API_KEY')}
            result=self.runner(command,input=prompt,text=True,capture_output=True,cwd=directory,env=env,timeout=120,check=True)
            if self.provider=='codex':
                events=[json.loads(line) for line in result.stdout.splitlines() if line.strip()]
                # Tool use would contaminate a benchmark, even if it returned a legal choice.
                if any(e.get('item',{}).get('type') in ('command_execution','mcp_tool_call','web_search','file_change') for e in events):raise ValueError('CLI attempted tool use; benchmark stopped')
                raw={'model':model,'events':events}
                usage=next((e['usage'] for e in reversed(events) if 'usage' in e),{})
                content=output.read_text()
            else:
                raw=json.loads(result.stdout)
                if raw.get('is_error'):raise ValueError('Claude CLI reported an error')
                content=raw.get('structured_output',raw.get('result'));usage=raw.get('usage',{})
            return content,raw,{'input_tokens':usage.get('input_tokens',0),'output_tokens':usage.get('output_tokens',0),'cached_input_tokens':usage.get('cache_read_input_tokens',usage.get('cached_input_tokens',0))},{'cli':self.provider,'model':model,'messages':messages,'schema':output_schema}
