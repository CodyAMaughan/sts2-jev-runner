"""Fast Monte Carlo of the Act 1 boss Vantom for a given deck, used to score drafting and
upgrade choices by what they do to the fight that ends most runs.

Vantom (from its decompiled state machine; game knowledge a player has): 173 HP, 8 Slippery
(each HP-damaging hit deals 1 and removes a stack), a fixed cycle Ink Blot 7 -> Inky Lance
6x2 -> Dismember 26 (+3 Wounds into the discard) -> Prepare (+2 Strength, no attack).
The player draws 5 cards a turn with 3 energy. Each turn picks the best playable subset by
the same objective as the live turn planner: HP lost now + boss damage/turn x effective boss
HP / our damage/turn (Slippery stacks count as extra HP). Card behaviour comes only from each
card's own numbers (damage, hits, Block, draw, energy, Vulnerable, Strength, HP loss).
Only visible deck contents are used; the shuffle is random per simulated fight.
"""
import itertools, random, re

BOSS_HP = 173
SLIPPERY = 8
CYCLE = [('attack', 7, 1), ('attack', 6, 2), ('dismember', 26, 1), ('buff', 0, 0)]
SLIP_VALUE = 5.0
BOSS_DPT = 13.1  # observed average Vantom damage per turn (ENEMY_DPT)


def card_model(c, deck_ids=()):
    c = c.get('card', c)
    v = c.get('variables') or {}
    text = c.get('text') or ''
    cid = c.get('id')
    typ = c.get('type')
    if typ in ('Status', 'Curse') or 'Unplayable' in text: return None
    cost = c.get('cost')
    x = 'X times' in text
    if not x and (not isinstance(cost, int) or cost < 0): return None
    # Effects inside an "If ..." sentence are conditional; count them only where the
    # simulator can check the condition (Dismantle vs a Vulnerable boss), else not at all.
    sentences = [x.strip() for x in re.split(r'[.\n]', text) if x.strip()]
    conditional = ' '.join(x for x in sentences if x.startswith('If '))
    vuln_twice = 'Vulnerable' in conditional and 'twice' in conditional
    dmg = 0; hits = 0
    if typ == 'Attack':
        dmg = v.get('Damage') or v.get('CalculatedDamage') or v.get('CalculationBase') or 0
        if cid == 'PERFECTED_STRIKE':
            dmg = (v.get('CalculationBase') or 6) + (v.get('ExtraDamage') or 2) * sum(1 for d in deck_ids if 'STRIKE' in d)
        hits = v.get('Repeat') or (2 if 'twice' in text else 1)
        if ('twice' in conditional or 'times' in conditional): hits = 1
    draw = v.get('Cards') or 0; energy = v.get('Energy') or 0
    if 'Hand' in conditional or 'Exhaust' in conditional or 'draw' in conditional.lower(): draw = energy = 0
    return dict(plating=(v.get('PlatingPower') or 0) if cid == 'STONE_ARMOR' else 0,
                mantle=(v.get('CrimsonMantlePower') or 0) if cid == 'CRIMSON_MANTLE' else 0, vuln_twice=vuln_twice, id=cid, cost=0 if x else cost, x=x, dmg=dmg, hits=hits, block=(v.get('Block') or 0),
                draw=draw, energy=energy, vuln=(v.get('VulnerablePower') or 0),
                str_turn=(v.get('StrengthPower') or 0) if cid in ('SETUP_STRIKE', 'FIGHT_ME') else 0,
                str_perm=(v.get('StrengthPower') or 0) if cid in ('INFLAME', 'DEMON_FORM') else 0,
                demon=cid == 'DEMON_FORM', hploss=(v.get('HpLoss') or 0), body_slam=cid == 'BODY_SLAM',
                exhaust='Exhaust' in text and typ != 'Attack', power=typ == 'Power')


def _deck_dpt(models):
    atk = [m for m in models if m and m['dmg'] > 0]
    if not atk: return 8.0
    share = len(atk) / max(1, len(models))
    per = sum(m['dmg'] * m['hits'] for m in atk) / len(atk)
    return max(8.0, min(5 * share, 3.0) * per)


def simulate(deck, hp, sims=200, seed=1, max_turns=25):
    """Returns (win_rate, mean_hp_lost, mean_turns). hp is the HP entering the fight."""
    ids = [(c.get('card', c)).get('id') for c in deck]
    base = [card_model(c, ids) for c in deck]
    P0 = _deck_dpt(base)
    rng = random.Random(seed)
    wins = 0; lost_total = 0.0; turns_total = 0
    for _ in range(sims):
        draw = list(range(len(base))); rng.shuffle(draw)
        models = list(base)
        discard = []; exhausted = set()
        boss, slip, bstr = BOSS_HP, SLIPPERY, 0
        vuln = 0; strength = 0; demon = 0; php = hp; turn = 0; plating = 0; mantle = 0
        while php > 0 and boss > 0 and turn < max_turns:
            move, mdmg, mhits = CYCLE[turn % 4]
            turn += 1
            strength += demon * 2
            start_block = mantle; php -= 1 if mantle else 0
            hand = []
            def pull(n):
                nonlocal draw, discard
                for _ in range(n):
                    if not draw:
                        if not discard: break
                        draw = discard; discard = []; rng.shuffle(draw)
                    hand.append(draw.pop())
            pull(5)
            # draw cards are played first (their draws resolve before the plan)
            energy = 3
            for i in list(hand):
                m = models[i]
                if m and m['draw'] and m['cost'] <= energy and m['dmg'] == 0 and m['block'] == 0:
                    energy -= m['cost']; energy += m['energy']; php -= m['hploss']
                    hand.remove(i); (exhausted.add(i) if m['exhaust'] else discard.append(i)); pull(m['draw'])
            incoming = (mdmg + bstr) * mhits if move in ('attack', 'dismember') else 0
            playable = [i for i in hand if models[i]]
            # order: powers/vuln/strength first, then block, then attacks (Body Slam last)
            def key(i):
                m = models[i]
                return (0 if (m['power'] or m['vuln'] or m['str_turn']) else 1 if m['block'] and not m['dmg'] else 2 if not m['body_slam'] else 3)
            best = None
            for r in range(len(playable) + 1):
                if r > 6: break
                for combo in itertools.combinations(sorted(playable, key=key), r):
                    e = energy + sum(models[i]['energy'] for i in combo)
                    xs = [i for i in combo if models[i]['x']]
                    cost = sum(models[i]['cost'] for i in combo)
                    if cost > e or len(xs) > 1: continue
                    xe = e - cost
                    blk = start_block; b = boss; s = slip; v = vuln; st = strength; hpl = 0; st_turn = 0
                    for i in combo:
                        m = models[i]
                        st += m['str_perm']; st_turn += m['str_turn']; hpl += m['hploss']
                        if m['vuln']: v = max(v, 0) + m['vuln']
                        blk += m['block']
                        if m['dmg'] or m['body_slam'] or m['x']:
                            per = (blk if m['body_slam'] else m['dmg']) + st + st_turn
                            per = int(per * (1.5 if v else 1))
                            n = xe if m['x'] else (2 if m['vuln_twice'] and v else m['hits'])
                            for _ in range(n):
                                if b <= 0: break
                                if s > 0: s -= 1; b -= 1
                                else: b -= per
                    pl = plating + sum(models[i]['plating'] for i in combo)
                    now = max(0, incoming - blk - pl) + hpl
                    heff = max(0, b) + SLIP_VALUE * s
                    score = now + (0 if b <= 0 else BOSS_DPT * heff / (P0 + 3 * (st - strength)))
                    if now >= php and b > 0: score += 1000
                    if best is None or score < best[0]: best = (score, combo, b, s, v, st, blk, now, xe)
            _, combo, boss, slip, vuln, new_str, blk, now, _ = best
            demon += sum(1 for i in combo if models[i]['demon'])
            plating += sum(models[i]['plating'] for i in combo); mantle += sum(models[i]['mantle'] for i in combo)
            if plating: plating -= 1  # Plating shrinks by 1 each turn
            strength = new_str - sum(models[i]['str_perm'] for i in combo if models[i]['demon'])
            for i in hand:
                if i in combo and models[i]['exhaust']: exhausted.add(i)
                else: discard.append(i)
            if boss <= 0: break
            php -= now
            if vuln: vuln -= 1
            if move == 'dismember':
                for _ in range(3): models.append(None); discard.append(len(models) - 1)
            if move == 'buff': bstr += 2
        if boss <= 0 and php > 0: wins += 1; lost_total += hp - php
        else: lost_total += hp
        turns_total += turn
    return wins / sims, lost_total / sims, turns_total / sims
