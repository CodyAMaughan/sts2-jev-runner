"""Count actual rules and audited effect handlers; tags include historical stale labels."""
from pathlib import Path
from collections import Counter
import re,json
root=Path(__file__).resolve().parent.parent
cards=json.loads((root/'cards.json').read_text())['cards']
groups={
 'Boast':{c['number'] for c in cards if 'Boast' in c['text']},
 'Wall':{c['number'] for c in cards if 'Wall' in c['text']},
 'Favor / generated-card support':{c['number'] for c in cards if re.search(r'\bFavors?\b|generated card',c['text'])},
 'Spin':{c['number'] for c in cards if 'Spin' in c['text']},
 'Bargain':{c['number'] for c in cards if 'Bargain' in c['text']},
 'Leverage':{c['number'] for c in cards if 'Leverage' in c['text']},
 'Status-specific support':{c['number'] for c in cards if re.search(r'\bStatus',c['text'])},
 'Exhaust themselves':{c['number'] for c in cards if c['text'].endswith('Exhaust.')},
 'Exhaust any other hand card':{2,13,20,23,29,37,39,45,50,63,69},
 'Exhaust other cards (including restricted targets)':{2,13,20,23,29,37,38,39,45,50,63,64,65,69},
 'Create Statuses without deliberately failing Boast':{5,6,15,19,30,43,47,60,66,67,70},
}
report={'scope':'80 reward cards; counts overlap; Basics/tokens/relics excluded','version':json.loads((root/'cards.json').read_text())['version'],'groups':{}}
lines=['# Mechanic representation — '+report['version'],'',report['scope']+'. Counts use rules text and audited effect handlers, not historical tags.','',
 '| Mechanic / role | Total | Common | Uncommon | Rare | Pool share |','|---|---:|---:|---:|---:|---:|']
for name,ids in groups.items():
 selected=[c for c in cards if c['number'] in ids];rarity=Counter(c['rarity'] for c in selected)
 report['groups'][name]={'count':len(ids),'rarities':dict(rarity),'cards':[{'number':c['number'],'name':c['name']} for c in selected]}
 lines.append(f"| {name} | {len(ids)} | {rarity['Common']} | {rarity['Uncommon']} | {rarity['Rare']} | {len(ids)/80:.1%} |")
lines += ['', 'Bargain: 7 cards with 11 unrestricted hand-Exhaust enablers (including the recurring Wall Power). No starter directly Exhausts another card. Bargain triggers once per physical card per combat; self-Exhaust and Ethereal do not trigger it.', '',
 'IOUs block Attacks while in hand, except cards with Spin. Status penalties placed on top arrive after the source card draws. Calling in Everything hits once per Favor and leaves those Favors in hand.']
# Explicit listing makes the scope and overlapping counts auditable.
for name,data in report['groups'].items():lines+=['','## '+name,'',', '.join(f"{c['number']}: {c['name']}" for c in data['cards'])]
out=root/'docs/balance'/('v'+report['version']);out.mkdir(parents=True,exist_ok=True)
(out/'mechanic-counts.json').write_text(json.dumps(report,indent=2)+'\n')
(out/'mechanic-counts.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines[:16]))
