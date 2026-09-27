"""Act 1 outlook simulator: how likely is this deck to beat Vantom, counting the HP it will
lose in the normal fights still ahead? Scores Act 1 drafting/upgrade/rest choices end to end,
so damage cards and Block cards are traded off by what they do to the whole act.

Each simulated trajectory plays the expected number of remaining hallway fights (drawn from
common Act 1 encounters with their decompiled move patterns), heals with Burning Blood if the
deck's owner has it, rests once before the boss if hurt, then fights Vantom. Same turn policy
as vantom_sim: the playable subset minimizing HP lost now + enemy damage/turn x effective HP /
our damage/turn. Visible deck contents and public move patterns only.
"""
import itertools, random
from vantom_sim import card_model, _deck_dpt, SLIP_VALUE

# name: (hp, [(damage, hits, block, strength_gain)] cycle, random_order)
NIBBIT = (44, [(12, 1, 0, 0), (6, 1, 5, 0), (0, 0, 0, 2)], False)
MAWLER = (72, [(14, 1, 0, 0), (4, 2, 0, 0), (0, 0, 0, 0)], True)
VINE_SHAMBLER = (61, [(6, 2, 0, 0), (8, 1, 0, 0), (16, 1, 0, 0)], False)
ASSASSIN = (19, [(10, 1, 0, 0)], False)
AXE = (20, [(5, 1, 5, 0), (12, 1, 0, 0)], False)
BRUTE = (31, [(7, 1, 0, 0), (0, 0, 0, 3)], False)
VANTOM = (173, [(7, 1, 0, 0), (6, 2, 0, 0), (26, 1, 0, 0), (0, 0, 0, 2)], False)
HALLWAY = [((NIBBIT, NIBBIT), 0.3), ((MAWLER,), 0.25), ((VINE_SHAMBLER,), 0.2), ((ASSASSIN, AXE, BRUTE), 0.25)]


def fight(models, hp, enemies, rng, P0, vantom=False, max_turns=25):
    """One fight. Returns (HP left (<=0 means dead), share of total enemy HP removed)."""
    draw = list(range(len(models))); rng.shuffle(draw)
    models = list(models); discard = []
    foes = []
    for (ehp, cycle, rnd) in enemies:
        foes.append({'hp': ehp, 'cycle': cycle, 'i': rng.randrange(len(cycle)) if rnd or len(enemies) > 1 else 0,
                     'str': 0, 'block': 0, 'slip': 8 if vantom else 0, 'vuln': 0,
                     'x': sum(d * h for d, h, _, _ in cycle) / len(cycle)})
    strength = 0; demon = 0; plating = 0; mantle = 0; turn = 0
    while hp > 0 and any(f['hp'] > 0 for f in foes) and turn < max_turns:
        turn += 1
        strength += demon * 2
        hand = []
        def pull(n):
            nonlocal draw, discard
            for _ in range(n):
                if not draw:
                    if not discard: break
                    draw = discard; discard = []; rng.shuffle(draw)
                hand.append(draw.pop())
        pull(5)
        energy = 3
        for i in list(hand):
            m = models[i]
            if m and m['draw'] and m['cost'] <= energy and m['dmg'] == 0 and m['block'] == 0:
                energy += m['energy'] - m['cost']; hp -= m['hploss']
                hand.remove(i); discard.append(i); pull(m['draw'])
        alive = [f for f in foes if f['hp'] > 0]
        moves = {id(f): f['cycle'][f['i'] % len(f['cycle'])] for f in alive}
        start_block = mantle
        if mantle: hp -= 1
        playable = [i for i in hand if models[i]]
        def key(i):
            m = models[i]
            return (0 if (m['power'] or m['vuln'] or m['str_turn']) else 1 if m['block'] and not m['dmg'] else 2 if not m['body_slam'] else 3)
        best = None
        for r in range(min(len(playable), 6) + 1):
            for combo in itertools.combinations(sorted(playable, key=key), r):
                e = energy + sum(models[i]['energy'] for i in combo)
                xs = [i for i in combo if models[i]['x']]
                cost = sum(models[i]['cost'] for i in combo)
                if cost > e or len(xs) > 1: continue
                xe = e - cost
                sim = [dict(hp=f['hp'], block=f['block'], slip=f['slip'], vuln=f['vuln']) for f in alive]
                blk = start_block; st = strength; st_turn = 0; hpl = 0
                for i in combo:
                    m = models[i]
                    st += m['str_perm']; st_turn += m['str_turn']; hpl += m['hploss']; blk += m['block']
                    if m['vuln']:
                        tgt = min((s for s in sim if s['hp'] > 0), key=lambda s: s['hp'], default=None)
                        if tgt: tgt['vuln'] += m['vuln']
                    if m['dmg'] or m['body_slam'] or m['x']:
                        n = xe if m['x'] else m['hits']
                        if m['vuln_twice'] and not m['x']:
                            focus = min((s for s in sim if s['hp'] > 0), key=lambda s: s['hp'], default=None)
                            n = 2 if focus and focus['vuln'] else 1
                        for _ in range(n):
                            live = [s for s in sim if s['hp'] > 0]
                            if not live: break
                            s = min(live, key=lambda s: s['hp'])  # focus the enemy closest to dying
                            per = (blk if m['body_slam'] else m['dmg']) + st + st_turn
                            per = int(per * (1.5 if s['vuln'] else 1))
                            absorbed = min(s['block'], per); s['block'] -= absorbed; per -= absorbed
                            if per > 0:
                                if s['slip'] > 0: s['slip'] -= 1; s['hp'] -= 1
                                else: s['hp'] -= per
                pl = plating + sum(models[i]['plating'] for i in combo)
                incoming = 0
                for f, s in zip(alive, sim):
                    if s['hp'] <= 0: continue
                    d, h, _, _ = moves[id(f)]
                    incoming += (d + f['str']) * h if d else 0
                now = max(0, incoming - blk - pl) + hpl
                fut = sum(f['x'] * (max(0, s['hp']) + SLIP_VALUE * s['slip']) for f, s in zip(alive, sim) if s['hp'] > 0) / (P0 + 3 * (st - strength))
                score = now + fut + (1000 if now >= hp else 0)
                if best is None or score < best[0]: best = (score, combo, sim, st, now)
        _, combo, sim, new_str, now = best
        demon += sum(1 for i in combo if models[i]['demon'])
        strength = new_str - sum(models[i]['str_perm'] for i in combo if models[i]['demon'])
        plating += sum(models[i]['plating'] for i in combo); mantle += sum(models[i]['mantle'] for i in combo)
        if plating: plating -= 1
        for i in hand: discard.append(i)
        for f, s in zip(alive, sim):
            f['hp'], f['slip'], f['vuln'] = s['hp'], s['slip'], max(0, s['vuln'] - 1)
            f['block'] = 0
        if not any(f['hp'] > 0 for f in foes): break
        hp -= now
        for f in alive:
            if f['hp'] <= 0: continue
            d, h, b, sg = moves[id(f)]
            f['block'] += b; f['str'] += sg
            if vantom and d == 26:
                for _ in range(3): models.append(None); discard.append(len(models) - 1)
            f['i'] += 1
    total = sum(e[0] for e in enemies)
    return hp, sum(e[0] - max(0, f['hp']) for e, f in zip(enemies, foes)) / total


def outlook(deck, hp, max_hp, floor, relic_ids=(), sims=150, seed=5):
    """(chance to beat Vantom after the rest of Act 1, mean HP entering Vantom, mean share
    of Vantom's HP removed: a continuous signal that still ranks decks when wins are rare)."""
    ids = [(c.get('card', c)).get('id') for c in deck]
    models = [card_model(c, ids) for c in deck]
    P0 = _deck_dpt(models)
    rng = random.Random(seed)
    burning = 'BURNING_BLOOD' in relic_ids
    fights_left = max(0, round((16 - floor) * 0.45))
    wins = 0; entry = 0.0; progress = 0.0
    pool = [e for e, _ in HALLWAY]; weights = [w for _, w in HALLWAY]
    for _ in range(sims):
        h = hp
        for _ in range(fights_left):
            enc = rng.choices(pool, weights)[0]
            h, _ = fight(models, h, enc, rng, P0)
            if h <= 0: break
            if burning: h = min(max_hp, h + 6)
        if h <= 0: continue
        if h < 0.9 * max_hp: h = min(max_hp, h + round(0.3 * max_hp))  # rest site before the boss
        entry += h
        left, share = fight(models, h, (VANTOM,), rng, P0, vantom=True)
        progress += share
        if left > 0: wins += 1
    return wins / sims, entry / sims, progress / sims
