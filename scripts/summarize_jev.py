#!/usr/bin/env python3
"""Summarize evidence without interpreting mock runs as model performance."""
import collections,json,statistics,sys
from pathlib import Path

def summarize(directory):
 p=Path(directory);path=p/'jev-decisions.jsonl'
 rows=[json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
 decisions=[r for r in rows if r.get('kind')=='decision'];responses=[r['response'] for r in decisions if r.get('response')]
 result=json.loads((p/'result.json').read_text()) if (p/'result.json').exists() else {}
 summary={'mode':next((r['mode'] for r in rows if r.get('kind')=='controller'),'unknown'),
          'result':result,'decision_count':len(decisions),
          'decision_kinds':dict(collections.Counter(r['observation']['kind'] for r in decisions)),
          'model_call_count':len(responses),
          'action_sources':dict(collections.Counter(r.get('source','jev' if r.get('response') else 'unknown') for r in decisions)),
          'models_reported':sorted({r['model'] for r in responses if 'model' in r}),
          'input_tokens':sum(r.get('usage',{}).get('input_tokens',0) for r in responses),
          'output_tokens':sum(r.get('usage',{}).get('output_tokens',0) for r in responses),
          'median_decision_seconds':statistics.median([r['latency_seconds'] for r in decisions if r.get('response')]) if responses else None,
          'low_confidence_count':sum(r['answers']['action'].get('confidence',1)<.4 for r in responses),
          'notes':'Confidence is model certainty, not win probability. Mock and replay runs are not new Jev balance evidence.'}
 (p/'jev-summary.json').write_text(json.dumps(summary,indent=2)+'\n');return summary
if __name__=='__main__':print(json.dumps(summarize(sys.argv[1]),indent=2))
