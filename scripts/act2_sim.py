"""Act 2 outlook simulator: chance this deck beats The Insatiable after the Act 2 hallway
fights still ahead. Same idea and turn policy as act1_sim (HP lost now + enemy damage/turn x
effective HP / our damage/turn), with the Act 2 encounter pool weighted by how often each
appeared in recorded runs and move patterns/HP from the decompiled monsters.

Mechanics modeled per enemy: attack cycles (fixed or random), Block gain, Strength gain,
Thorns turns (Spiny Toad), a per-hit damage cap (Exoskeleton's Hard to Kill), persistent Block
(Tunneler), reviving minions (Parafright: the fight ends when its leader dies), escaping
(Thieving Hopper leaves after 4 turns), sleeping (Slumbering Beetle), and The Insatiable's
Sandpit as an energy tax (Frantic Escape costs 1 more each time it is played).
Visible deck contents and public move patterns only.
"""
import itertools, random
from vantom_sim import card_model, _deck_dpt, SLIP_VALUE


def E(hp, cycle, random_order=False, **flags):
    return dict(hp=hp, cycle=cycle, random=random_order, **flags)

# cycle entries: (damage, hits, block, strength, thorns)
HUNTER = E(121, [(0, 0, 0, 0, 0), (17, 1, 0, 0, 0), (7, 3, 0, 0, 0), (7, 3, 0, 0, 0)], tender=True)
TOAD = E(116, [(0, 0, 0, 0, 0), (23, 1, 0, 0, 5), (17, 1, 0, 0, 0)])  # Thorns only while Explosion is queued
OBSCURA = E(123, [(10, 1, 0, 0, 0), (6, 1, 6, 0, 0), (0, 0, 0, 3, 0)], True, leader=True)
PARAFRIGHT = E(21, [(16, 1, 0, 0, 0)], revive=True, minion=True)
MYTE = E(61, [(0, 0, 0, 0, 0), (13, 1, 0, 0, 0), (4, 1, 0, 2, 0)], toxic=True)
ROCK = E(45, [(15, 1, 0, 0, 0)])
SILK = E(40, [(4, 2, 0, 0, 0), (0, 0, 0, 0, 0)])
NECTAR = E(35, [(3, 1, 0, 0, 0), (0, 0, 0, 15, 0), (3, 1, 0, 0, 0)])
EGG = E(21, [(0, 0, 0, 0, 0)])
BEETLE = E(86, [(16, 1, 0, 2, 0)], sleep=3, block0=15)
CHOMPER = E(60, [(8, 2, 0, 0, 0), (0, 0, 0, 0, 0)], True)
TUNNELER = E(87, [(13, 1, 0, 0, 0), (0, 0, 32, 0, 0), (23, 1, 0, 0, 0)], persist=True)
EXO = E(24, [(1, 3, 0, 0, 0), (8, 1, 0, 0, 0)], True, cap=9)
HOPPER = E(79, [(17, 1, 0, 0, 0), (0, 0, 0, 0, 0), (21, 1, 0, 0, 0), (14, 1, 0, 0, 0)], escape=4)
LOUSE = E(134, [(9, 1, 0, 0, 0), (14, 1, 0, 0, 0), (0, 0, 14, 5, 0)])
OVICOPTER = E(124, [(16, 1, 0, 0, 0), (7, 1, 0, 0, 0), (0, 0, 0, 3, 0)])
INSATIABLE = E(321, [(0, 0, 0, 0, 0), (8, 2, 0, 0, 0), (28, 1, 0, 0, 0), (0, 0, 0, 2, 0)], sandpit=True)
HALLWAY = [((HOPPER,), 11.0), ((TUNNELER,), 10.7), ((EXO, EXO, EXO), 9.6), ((CHOMPER, CHOMPER), 7.8), ((HUNTER,), 7.0),
           ((OBSCURA, PARAFRIGHT), 6.8), ((TOAD,), 6.8), ((LOUSE,), 6.8), ((EXO, EXO, EXO, EXO), 6.4), ((EGG, ROCK), 6.1),
           ((MYTE, MYTE), 5.2), ((ROCK, SILK, BEETLE), 4.9), ((NECTAR, ROCK), 3.3), ((OVICOPTER,), 2.8), ((NECTAR, ROCK, SILK), 2.0)]


POWER = 1.5  # global multiplier on card damage/Block, fit so simulated hallway HP loss matches recorded play


def fight(models, hp, enemies, rng, P0, max_turns=25):
    """One fight: (HP left (<=0 dead), share of the leaders' HP removed)."""
    draw = list(range(len(models))); rng.shuffle(draw)
    models = list(models); discard = []
    foes = [dict(spec=e, hp=e['hp'], i=rng.randrange(len(e['cycle'])) if e['random'] else 0, str=0,
                 block=e.get('block0', 0), vuln=0, sleep=e.get('sleep', 0), down=0,
                 x=sum(c[0] * c[1] for c in e['cycle']) / len(e['cycle'])) for e in enemies]
    leaders = [f for f in foes if not f['spec'].get('minion')]
    strength = 0; demon = 0; plating = 0; mantle = 0; turn = 0; escapes = 0; toxic = 0
    sandpit = any(e.get('sandpit') for e in enemies)
    while hp > 0 and any(f['hp'] > 0 for f in leaders) and turn < max_turns:
        turn += 1
        strength += demon * 2
        if any(f['spec'].get('escape') and f['hp'] > 0 and turn > f['spec']['escape'] for f in foes): break  # it fled
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
        if sandpit and turn >= 2:  # Frantic Escape each turn, 1 more energy every third turn
            energy -= min(3, 1 + (turn - 2) // 3)
        for i in list(hand):
            m = models[i]
            if m and m['draw'] and m['cost'] <= energy and m['dmg'] == 0 and m['block'] == 0:
                energy += m['energy'] - m['cost']; hp -= m['hploss']
                hand.remove(i); discard.append(i); pull(m['draw'])
        for f in foes:  # reviving minions come back a turn after dying
            if f['hp'] <= 0 and f['spec'].get('revive'):
                f['down'] += 1
                if f['down'] >= 2: f['hp'] = f['spec']['hp']; f['down'] = 0
        alive = [f for f in foes if f['hp'] > 0]
        moves = {id(f): (0, 0, 0, 0, 0) if f['sleep'] > 0 else f['cycle'][f['i'] % len(f['cycle'])] if 'cycle' in f else f['spec']['cycle'][f['i'] % len(f['spec']['cycle'])] for f in alive}
        start_block = mantle
        if mantle: hp -= 1
        tender = any(f['spec'].get('tender') for f in alive)
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
                sim = [dict(hp=f['hp'], block=f['block'], vuln=f['vuln'], sleep=f['sleep'], f=f) for f in alive]
                blk = start_block; st = strength; st_turn = 0; hpl = 0; thorn_hits = 0; played = 0
                for i in combo:
                    m = models[i]; played += 1
                    st += m['str_perm']; st_turn += m['str_turn']; hpl += m['hploss']
                    blk += max(0, int(POWER * m['block']) - (played - 1 if tender else 0))
                    if m['vuln']:
                        tgt = min((s for s in sim if s['hp'] > 0 and not s['sleep']), key=lambda s: s['hp'], default=None)
                        if tgt: tgt['vuln'] += m['vuln']
                    if m['dmg'] or m['body_slam'] or m['x']:
                        n = xe if m['x'] else m['hits']
                        for _ in range(n):
                            awake = [s for s in sim if s['hp'] > 0 and not s['sleep'] and not s['f']['spec'].get('revive')]
                            live = awake or [s for s in sim if s['hp'] > 0]
                            if not live: break
                            # focus the leader-relevant enemy closest to dying (minions only if they hit hard)
                            s = min(live, key=lambda s: s['hp'])
                            per = (blk if m['body_slam'] else int(POWER * m['dmg'])) + st + st_turn - (played - 1 if tender else 0)
                            per = int(max(0, per) * (1.5 if s['vuln'] else 1))
                            absorbed = min(s['block'], per); s['block'] -= absorbed; per -= absorbed
                            if per > 0:
                                cap = s['f']['spec'].get('cap')
                                s['hp'] -= min(per, cap) if cap else per
                                if s['sleep']: s['sleep'] = max(0, s['sleep'] - 1)
                            thorn_hits += moves[id(s['f'])][4]
                pl = plating + sum(models[i]['plating'] for i in combo)
                incoming = thorn_hits + 5 * toxic
                for f, s in zip(alive, sim):
                    if s['hp'] <= 0: continue
                    d, h, _, _, _ = moves[id(f)]
                    incoming += (d + f['str']) * h if d else 0
                now = max(0, incoming - blk - pl) + hpl
                leaders_left = sum(max(0, s['hp']) + s['block'] for f, s in zip(alive, sim) if not f['spec'].get('minion'))
                p = P0 + 3 * (st - strength)
                fut = sum(f['x'] * ((max(0, s['hp']) + s['block']) if not f['spec'].get('revive') else leaders_left) for f, s in zip(alive, sim) if s['hp'] > 0 or f['spec'].get('revive')) / p
                score = now + fut + (1000 if now >= hp else 0)
                if best is None or score < best[0]: best = (score, combo, sim, st, now)
        _, combo, sim, new_str, now = best
        demon += sum(1 for i in combo if models[i]['demon'])
        strength = new_str - sum(models[i]['str_perm'] for i in combo if models[i]['demon'])
        plating += sum(models[i]['plating'] for i in combo); mantle += sum(models[i]['mantle'] for i in combo)
        if plating: plating -= 1
        for i in hand: discard.append(i)
        for f, s in zip(alive, sim):
            f['hp'], f['vuln'], f['sleep'] = s['hp'], max(0, s['vuln'] - 1), s['sleep']
            if not f['spec'].get('persist'): f['block'] = 0
            else: f['block'] = s['block']
        if not any(f['hp'] > 0 for f in leaders): break
        hp -= now
        toxic = 0
        for f in alive:
            if f['hp'] <= 0: continue
            if f['sleep'] > 0: f['sleep'] -= 1; continue
            d, h, b, sg, _ = moves[id(f)]
            f['block'] += b; f['str'] += sg
            if f['spec'].get('toxic') and d == 0 and sg == 0: toxic += 1  # Toxic cards in hand next turn
            f['i'] += 1
    total = sum(e['hp'] for e in enemies if not e.get('minion'))
    return hp, sum(f['spec']['hp'] - max(0, f['hp']) for f in leaders) / total


def outlook(deck, hp, max_hp, floor, relic_ids=(), sims=120, seed=5, pre_boss_rest=True):
    """(chance to beat The Insatiable after the rest of Act 2, mean HP entering it, mean share of its HP removed)."""
    ids = [(c.get('card', c)).get('id') for c in deck]
    models = [card_model(c, ids) for c in deck]
    P0 = _deck_dpt(models)
    rng = random.Random(seed)
    burning = 'BURNING_BLOOD' in relic_ids
    fights_left = max(0, round((32 - floor) * 0.45))
    pool = [e for e, _ in HALLWAY]; weights = [w for _, w in HALLWAY]
    wins = 0; entry = 0.0; progress = 0.0
    for _ in range(sims):
        h = hp
        for _ in range(fights_left):
            h, _ = fight(models, h, rng.choices(pool, weights)[0], rng, P0)
            if h <= 0: break
            if burning: h = min(max_hp, h + 6)
        if h <= 0: continue
        if pre_boss_rest and h < 0.9 * max_hp: h = min(max_hp, h + round(0.3 * max_hp))
        entry += h
        left, share = fight(models, h, (INSATIABLE,), rng, P0)
        progress += share
        if left > 0: wins += 1
    return wins / sims, entry / sims, progress / sims
