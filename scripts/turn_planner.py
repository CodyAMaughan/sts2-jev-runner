"""Turn planner: score whole-turn card lines by expected total HP lost over the fight.

The objective (the user's framing): HP lost in a fight = HP lost per turn x turns, and
turns ~= remaining enemy HP / our damage per turn. So a line is scored as

    HP lost this turn  +  sum over surviving enemies of  X_e * H_e / P

where X_e is enemy e's damage per turn, H_e its HP left after the line, and P our
expected damage per turn. Block is worth 1 per point of prevented damage; damage is
worth X_e / P per point; killing an enemy removes its attack this turn outright.

Only visible state is used (hand, energy, intents, powers, deck list). Draws are not
simulated: a draw card gets a flat estimated value and the planner is simply re-run on
the next decision, when the drawn cards are known. Situations the model cannot price
(e.g. Tender, Sandpit, Personal Hive, revives) return supported=False so Jev decides.
"""
import re

DEFER_ENEMY_POWERS = {'PERSONAL_HIVE_POWER', 'VITAL_SPARK_POWER', 'ILLUSION_POWER', 'REATTACH_POWER',
                      'SLUMBER_POWER', 'CURL_UP_POWER', 'IMBALANCED_POWER', 'HATCH_POWER', 'INFESTED_POWER', 'SWIPE_POWER'}
DEFER_PLAYER_POWERS = {'TENDER_POWER', 'NO_BLOCK_POWER', 'TANGLED_POWER', 'DUPLICATION_POWER', 'ONE_TWO_PUNCH_POWER',
                       'GIGANTIFICATION_POWER', 'JUGGLING_POWER', 'RUPTURE_POWER', 'VIGOR_POWER', 'FREE_ATTACK_POWER'}
# Cards whose value the simulator cannot see; lines may still include them, at a neutral value.
OPAQUE = {'HAVOC', 'CASCADE', 'DISCOVERY', 'INFERNAL_BLADE', 'ARMAMENTS', 'BURNING_PACT', 'TRUE_GRIT', 'FIEND_FIRE',
          'SEEKER_STRIKE', 'HEADBUTT', 'FORGOTTEN_RITUAL', 'THINKING_AHEAD', 'UPPERCUT'}
MAX_NODES = 40000
# Typical attack damage per turn by enemy, averaged over recorded Jev fights (jev-ironclad-11*
# batches): the kind of "this enemy hits for about N a turn" knowledge a practiced player has.
# Used as a prior for future turns, blended with what this fight has shown so far.
ENEMY_DPT = {"ASSASSIN_RUBY_RAIDER": 10.0, "AXE_RUBY_RAIDER": 6.7, "BOWLBUG_EGG": 7.0, "BOWLBUG_NECTAR": 7.7, "BOWLBUG_ROCK": 12.1, "BOWLBUG_SILK": 3.6, "BRUTE_RUBY_RAIDER": 5.2, "BYRDONIS": 17.5, "CHOMPER": 8.0, "CROSSBOW_RUBY_RAIDER": 5.5, "CUBEX_CONSTRUCT": 8.9, "DECIMILLIPEDE_SEGMENT_BACK": 9.2, "DECIMILLIPEDE_SEGMENT_FRONT": 9.3, "DECIMILLIPEDE_SEGMENT_MIDDLE": 9.0, "EXOSKELETON": 4.9, "EYE_WITH_TEETH": 0.0, "FLYCONID": 8.7, "FOGMOG": 9.3, "FUZZY_WURM_CRAWLER": 7.1, "HUNTER_KILLER": 16.4, "INFESTED_PRISM": 12.4, "INKLET": 5.3, "LEAF_SLIME_M": 3.4, "LEAF_SLIME_S": 1.6, "LOUSE_PROGENITOR": 10.3, "MAWLER": 9.9, "MYTE": 6.1, "NIBBIT": 7.1, "OVICOPTER": 11.2, "PARAFRIGHT": 18.2, "PHROG_PARASITE": 7.4, "SHRINKER_BEETLE": 6.4, "SLITHERING_STRANGLER": 4.5, "SLUMBERING_BEETLE": 10.8, "SNAPPING_JAXFRUIT": 7.0, "SPINY_TOAD": 11.8, "THE_INSATIABLE": 15.8, "THE_OBSCURA": 6.1, "THIEVING_HOPPER": 10.8, "TOUGH_EGG": 3.1, "TRACKER_RUBY_RAIDER": 5.1, "TUNNELER": 13.1, "TWIG_SLIME_M": 5.2, "TWIG_SLIME_S": 4.0, "VANTOM": 13.1, "VINE_SHAMBLER": 11.4, "WRIGGLER": 3.5}
PRIOR_WEIGHT = 3
DEATH_PENALTY = 1000.0
SLIPPERY_HIT_VALUE = 5.0


def _powers(creature):
    return {p.get('id'): p.get('amount') or 0 for p in (creature or {}).get('powers') or []}


def _intent_damage(enemy):
    return sum(i.get('total_damage') or 0 for i in enemy.get('intents') or [] if i.get('type') == 'Attack')


def _cap(text):
    m = re.search(r'to \[blue\](\d+)\[/blue\]', text or '')
    return int(m.group(1)) if m else None


def expected_damage_per_turn(state):
    """P: rough damage per turn from the deck's attacks (a 5-card hand, energy-limited)."""
    deck = state.get('deck') or []
    energy = max(3, state.get('energy') or 3)
    attacks = []
    for c in deck:
        c = c.get('card', c)
        if c.get('type') != 'Attack': continue
        v = c.get('variables') or {}
        dmg = (v.get('Damage') or v.get('CalculatedDamage') or 0) * (v.get('Repeat') or (2 if 'twice' in (c.get('text') or '') else 1))
        cost = c.get('cost') if isinstance(c.get('cost'), int) and c.get('cost') > 0 else 1
        attacks.append((dmg, cost))
    if not deck or not attacks: return 12.0
    share = len(attacks) / len(deck)
    per_card = sum(d for d, _ in attacks) / len(attacks)
    per_cost = sum(c for _, c in attacks) / len(attacks)
    strength = _powers(state.get('player')).get('STRENGTH_POWER') or 0
    plays = min(5 * share, energy / per_cost)
    return max(6.0, plays * (per_card + strength))


class Line:
    __slots__ = ('energy', 'used', 'hp', 'block', 'vuln', 'slip', 'artifact', 'pblock', 'hploss', 'thorns_taken',
                 'strength', 'draws', 'opaque', 'plan', 'inflame', 'dex', 'potions', 'weakened', 'shackle', 'sandpit')

    def copy(self):
        n = Line()
        for k in self.__slots__:
            v = getattr(self, k)
            setattr(n, k, list(v) if isinstance(v, list) else (set(v) if isinstance(v, set) else v))
        return n


# Potions the simulator can price. Each use also costs potion_cost HP-equivalents (the
# option value of keeping it), so a potion is only drunk when the line saves more than that.
POTIONS = {'BLOCK_POTION', 'FIRE_POTION', 'EXPLOSIVE_AMPOULE', 'SPEED_POTION', 'DEXTERITY_POTION', 'FLEX_POTION',
           'STRENGTH_POTION', 'VULNERABLE_POTION', 'WEAK_POTION', 'ENERGY_POTION', 'FYSH_OIL', 'SHACKLING_POTION',
           'HEART_OF_IRON', 'POTION_OF_BINDING'}


def _num(text, default=0):
    m = re.search(r'\[blue\](\d+)\[/blue\]', text or '')
    return int(m.group(1)) if m else default


def plan(obs, history=None, draw_value=None, potion_cost=9.0, rev=3):
    st = obs.get('state') or {}
    if obs.get('kind') != 'combat': return {'supported': False, 'reason': 'not combat'}
    player = st.get('player') or {}
    ppow = _powers(player)
    enemies = st.get('enemies') or []
    alive = [i for i, e in enumerate(enemies) if (e.get('creature') or {}).get('hp', 0) > 0]
    if not alive: return {'supported': False, 'reason': 'no enemies'}
    for e in enemies:
        bad = (DEFER_ENEMY_POWERS | ({'SANDPIT_POWER'} if rev < 4 else set())).intersection(_powers(e.get('creature')))
        if bad: return {'supported': False, 'reason': 'enemy power ' + ','.join(sorted(bad))}
    bad = DEFER_PLAYER_POWERS.intersection(ppow)
    if bad: return {'supported': False, 'reason': 'player power ' + ','.join(sorted(bad))}
    hand_ids = [((h.get('card', h)) or {}).get('id') for h in st.get('hand') or []]
    if rev < 4 and 'FRANTIC_ESCAPE' in hand_ids: return {'supported': False, 'reason': 'Frantic Escape'}

    P = expected_damage_per_turn(st)
    dex = ppow.get('DEXTERITY_POWER') or 0
    frail = 'FRAIL_POWER' in ppow
    weak_self = 'WEAK_POWER' in ppow
    # X_e: an enemy's damage per future turn.
    X = {}
    for i in alive:
        e = enemies[i]; name = e['creature'].get('name')
        cur = _intent_damage(e)
        seen = (history or {}).get(name) or []
        # This turn's spike is already in "HP lost now"; future turns cost the average,
        # estimated from the enemy's typical output blended with this fight's history.
        prior = ENEMY_DPT.get(name)
        if prior is None:  # unseen enemy: ~0.15 x max HP is the median ratio in ENEMY_DPT
            prior = 0.15 * e['creature']['max_hp'] if e['creature'].get('max_hp') else cur
        X[i] = max((prior * PRIOR_WEIGHT + sum(seen)) / (PRIOR_WEIGHT + len(seen)), 3.0)
    minions = {i for i in alive if 'MINION_POWER' in _powers(enemies[i]['creature'])}
    leaders = [i for i in alive if i not in minions]

    base = Line()
    base.energy = st.get('energy') or 0
    base.used = set(); base.plan = []
    base.hp = [(enemies[i]['creature'].get('hp') or 0) if i in alive else 0 for i in range(len(enemies))]
    base.block = [(enemies[i]['creature'].get('block') or 0) for i in range(len(enemies))]
    ep = [_powers(e.get('creature')) for e in enemies]
    base.vuln = [p.get('VULNERABLE_POWER') or 0 for p in ep]
    base.slip = [p.get('SLIPPERY_POWER') or 0 for p in ep]
    base.artifact = [p.get('ARTIFACT_POWER') or 0 for p in ep]
    htk = [(_cap(next((pp.get('text') for pp in (e.get('creature') or {}).get('powers') or [] if pp.get('id') == 'HARD_TO_KILL_POWER'), '')) if 'HARD_TO_KILL_POWER' in ep[k] else None) for k, e in enumerate(enemies)]
    thorns = [p.get('THORNS_POWER') or 0 for p in ep]
    start_vuln = list(base.vuln)
    base.pblock = player.get('block') or 0
    base.hploss = 0; base.thorns_taken = 0; base.strength = 0; base.draws = 0; base.opaque = 0; base.inflame = 0
    base.dex = 0; base.potions = 0; base.weakened = [False] * len(enemies); base.shackle = [0] * len(enemies)
    already_weak = ['WEAK_POWER' in p for p in [_powers(e.get('creature')) for e in enemies]]
    # The Insatiable's Sandpit: -1 at the start of each enemy turn, instant death at 0;
    # each Frantic Escape played adds 1 (and costs 1 more next time).
    sandpits = [p.get('SANDPIT_POWER') for p in ep if 'SANDPIT_POWER' in p]
    base.sandpit = min(sandpits) if sandpits else None
    toxic_in_hand = sum(1 for h in hand_ids if h == 'TOXIC')
    plating = ppow.get('PLATING_POWER') or 0
    if draw_value is None: draw_value = 0.35 * P / 5.0  # damage-equivalent of an unknown drawn card

    options = []
    for a in obs.get('actions') or []:
        o = a['option']
        if o.get('action') == 'use_potion' and o.get('id') in POTIONS:
            options.append((a['id'], ('potion', o.get('slot')), o.get('enemy_index', -1),
                            {'id': o['id'], 'type': 'Potion', 'cost': 0, 'text': o.get('text') or ''}))
            continue
        if o.get('action') != 'play_card': continue
        c = o.get('card') or {}
        options.append((a['id'], o.get('hand_index'), o.get('enemy_index', -1), c))

    def hit_damage(line, k, per_hit):
        """HP an enemy loses from one hit of per_hit (after its Block, Slippery, Hard to Kill)."""
        if line.hp[k] <= 0: return 0
        dmg = per_hit
        absorbed = min(line.block[k], dmg); line.block[k] -= absorbed; dmg -= absorbed
        if dmg <= 0: return 0
        if line.slip[k] > 0: line.slip[k] -= 1; dmg = 1
        if htk[k] is not None: dmg = min(dmg, htk[k])
        dmg = min(dmg, line.hp[k]); line.hp[k] -= dmg
        return dmg

    def drink(line, aid, hidx, target, c):
        n = line.copy(); n.used.add(hidx); n.plan.append(aid); n.potions += 1
        pid, text, amt = c['id'], c.get('text') or '', _num(c.get('text'))
        tgt = [target] if target is not None and target >= 0 and target in alive else alive[:1]
        if pid == 'BLOCK_POTION': n.pblock += amt or 12
        elif pid == 'HEART_OF_IRON': n.pblock += amt or 7  # Plating: Block at end of this turn (later turns not credited)
        elif pid in ('SPEED_POTION', 'DEXTERITY_POTION'): n.dex += amt or 2
        elif pid in ('FLEX_POTION', 'STRENGTH_POTION'): n.strength += amt or 2; n.inflame += (amt or 2) if pid == 'STRENGTH_POTION' else 0
        elif pid == 'FYSH_OIL': n.strength += 1; n.inflame += 1; n.dex += 1
        elif pid == 'ENERGY_POTION': n.energy += 2
        elif pid == 'FIRE_POTION':
            for k in tgt: hit_damage(n, k, amt or 20)
        elif pid == 'EXPLOSIVE_AMPOULE':
            for k in alive: hit_damage(n, k, amt or 10)
        elif pid in ('VULNERABLE_POTION', 'POTION_OF_BINDING'):
            for k in (alive if pid == 'POTION_OF_BINDING' else tgt):
                if n.artifact[k] > 0: n.artifact[k] -= 1
                else: n.vuln[k] += amt or 1
        if pid in ('WEAK_POTION', 'POTION_OF_BINDING'):
            for k in (alive if pid == 'POTION_OF_BINDING' else tgt):
                if n.artifact[k] > 0: n.artifact[k] -= 1
                else: n.weakened[k] = True
        if pid == 'SHACKLING_POTION':
            for k in alive: n.shackle[k] += amt or 7
        return n

    def apply(line, aid, hidx, target, c):
        if c.get('type') == 'Potion': return drink(line, aid, hidx, target, c)
        v = c.get('variables') or {}
        text = c.get('text') or ''
        cid = c.get('id')
        cost = c.get('cost')
        x_cost = 'X times' in text or ' X ' in text
        if x_cost: cost = line.energy
        if not isinstance(cost, int) or cost < 0: return None
        if cost > line.energy: return None
        n = line.copy(); n.energy -= cost; n.used.add(hidx); n.plan.append(aid)
        if cid in OPAQUE: n.opaque += 1
        if cid == 'FRANTIC_ESCAPE' and n.sandpit is not None: n.sandpit += 1
        n.energy += v.get('Energy') or 0
        n.hploss += v.get('HpLoss') or 0
        n.draws += v.get('Cards') or 0 if c.get('type') != 'Status' else 0
        if 'Block' in v and c.get('type') in ('Skill', 'Attack'):
            b = (v['Block'] or 0) + dex + line.dex
            if frail: b = int(b * 0.75)
            n.pblock += max(0, b)
        if c.get('type') == 'Attack':
            hits = v.get('Repeat') or (2 if 'twice' in text else 1)
            if x_cost: hits = cost
            per_hit = c.get('preview_damage_per_hit')
            base_dmg = v.get('CalculatedDamage') or v.get('Damage') or 0
            if cid == 'BODY_SLAM':  # damage equals current Block, so Block played first counts
                base_dmg = n.pblock; per_hit = None
            if per_hit is None:
                per_hit = (base_dmg + (_powers(player).get('STRENGTH_POWER') or 0)) * (0.75 if weak_self else 1)
            aoe = 'ALL enemies' in text
            random_target = 'random enemy' in text
            targets = [k for k in alive] if aoe else ([target] if target is not None and target >= 0 else [alive[0]])
            for k in targets:
                ph = per_hit
                if aoe or random_target or target is None or target < 0:
                    ph = (base_dmg + (_powers(player).get('STRENGTH_POWER') or 0)) * (0.75 if weak_self else 1) * (1.5 if start_vuln[k] else 1)
                if n.vuln[k] and not start_vuln[k]: ph *= 1.5
                ph += n.strength * (1.5 if n.vuln[k] else 1) * (0.75 if weak_self else 1)
                h = hits
                if random_target and len(alive) > 1:
                    # split the random hits across living enemies (expected value)
                    for kk in alive:
                        for _ in range(max(1, round(hits / len(alive)))):
                            hit_damage(n, kk, ph)
                            n.thorns_taken += thorns[kk]
                    break
                for _ in range(int(h)):
                    hit_damage(n, k, ph)
                    n.thorns_taken += thorns[k]
        vp = v.get('VulnerablePower') or 0
        if vp:
            vt = alive if 'ALL enemies' in text else ([target] if target is not None and target >= 0 else [])
            for k in vt:
                if n.artifact[k] > 0: n.artifact[k] -= 1
                else: n.vuln[k] += vp
        sl = v.get('StrengthLoss') or 0  # Dark Shackles: the target hits for less this turn
        if sl and target is not None and target >= 0: n.shackle[target] += sl
        sp = v.get('StrengthPower') or 0
        if sp and cid in ('SETUP_STRIKE', 'INFLAME', 'FIGHT_ME'):
            n.strength += sp
            if cid == 'INFLAME': n.inflame += sp
        return n

    def score(line):
        dead = {k for k in alive if line.hp[k] <= 0}
        combat_over = bool(leaders) and all(k in dead for k in leaders)
        def hit_now(k):
            d = _intent_damage(enemies[k])
            if d and line.shackle[k]: d = max(0, d - line.shackle[k])
            if line.weakened[k] and not already_weak[k]: d = int(d * 0.75)
            return d
        incoming = 0 if combat_over else sum(hit_now(k) for k in alive if k not in dead)
        incoming += line.thorns_taken + 5 * max(0, toxic_in_hand)
        block = line.pblock + plating
        hp_now = max(0, incoming - block) + line.hploss
        p = P + 3 * line.inflame
        future = 0.0
        rate = sum(X[k] for k in alive if k not in dead) / p
        if not combat_over:
            for k in alive:
                if k in dead: continue
                # Each Slippery stack left will eat a future hit (it deals 1 instead of ~6).
                h = line.hp[k] + line.block[k] + SLIPPERY_HIT_VALUE * line.slip[k]
                extra_vuln = max(0, min(line.vuln[k], 3) - max(start_vuln[k] - 1, 0) - 1)
                h = max(0.0, h - 0.5 * p * extra_vuln / max(1, len(alive) - len(dead)))
                future += X[k] * h / p
                if line.weakened[k] and not already_weak[k]: future -= 0.25 * X[k] * min(2.0, h / p)
        future -= line.draws * draw_value * rate
        # HP is not linear at zero: a line that dies this turn loses the run, so any
        # surviving line must beat it regardless of the damage math.
        death = DEATH_PENALTY if hp_now >= (player.get('hp') or 0) else 0.0
        if line.sandpit is not None and not combat_over:
            if line.sandpit < 2: death = DEATH_PENALTY
            # Surplus Sandpit is a future Frantic Escape (and its energy) not needed later.
            else: future -= (line.sandpit - 2) * (p / 3.0) * rate
        return hp_now + future + potion_cost * line.potions + death, hp_now, future

    best = {}
    nodes = [0]
    best_line = [None, None]

    def dfs(line, first):
        nodes[0] += 1
        s = score(line)
        key = first or 'end_turn'
        if key not in best or s[0] < best[key][0]:
            best[key] = (s[0], s[1], s[2], list(line.plan))
        if best_line[0] is None or s[0] < best_line[0][0]:
            best_line[0] = (s[0], s[1], s[2], list(line.plan))
        if nodes[0] >= MAX_NODES: return
        tried = set()
        for aid, hidx, target, c in options:
            if hidx in line.used: continue
            sig = (c.get('id'), c.get('upgraded'), target, c.get('cost'))
            if sig in tried: continue  # identical copies of a card are interchangeable
            tried.add(sig)
            n = apply(line, aid, hidx, target, c)
            if n is None: continue
            dfs(n, first or aid)

    dfs(base, None)
    end = [a['id'] for a in obs.get('actions') or [] if a['option'].get('action') == 'end_turn']
    scores = {}
    sig_best = {}
    for aid, hidx, target, c in options:
        if aid in best: sig_best[(c.get('id'), c.get('upgraded'), target, c.get('cost'))] = best[aid][0]
    for aid, hidx, target, c in options:
        sig = (c.get('id'), c.get('upgraded'), target, c.get('cost'))
        if sig in sig_best: scores[aid] = sig_best[sig]
    if end and 'end_turn' in best: scores[end[0]] = best['end_turn'][0]
    top = best_line[0]
    return {'supported': True, 'P': round(P, 1), 'X': {enemies[k]['creature'].get('name'): round(X[k], 1) for k in alive},
            'scores': {k: round(v, 2) for k, v in scores.items()}, 'best_plan': top[3], 'best_score': round(top[0], 2),
            'best_hp_now': round(top[1], 2), 'nodes': nodes[0],
            'opaque_in_best': sum(1 for aid in top[3] for o in options if o[0] == aid and o[3].get('id') in OPAQUE)}
