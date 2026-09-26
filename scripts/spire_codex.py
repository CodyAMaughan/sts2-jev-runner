"""Community card/relic stats from Spire Codex (spire-codex.com), a public,
unauthenticated API built by decompiling the game and aggregating submitted
runs. Used to give Jev real pick-context ("this card wins in 31% of the
45,924 runs it's appeared in") instead of no signal at all on card rewards.

Network calls are short-timeout and fail silent: a slow or unreachable API
must never stall or break a live run. Results are cached for the process
lifetime — the same common cards get offered repeatedly within one run and
across a batch, and this stays well inside the API's published rate limit
(300 requests per window, confirmed live) either way.
"""
import urllib.request, urllib.error, json

API = 'https://spire-codex.com/api'
_cache = {}


def item_stats(item_type, item_id, timeout=3):
    """{'count': int, 'winrate': float} for one card/relic's own community
    sample, or None if unavailable (no data, timeout, network error, bad
    response). item_type is 'cards' or 'relics'."""
    key = (item_type, item_id)
    if key in _cache:
        return _cache[key]
    result = None
    try:
        req = urllib.request.Request(f'{API}/pairings/{item_type}/{item_id}',
                                      headers={'User-Agent': 'Mozilla/5.0 (compatible; Dealmaker-Jev-Controller/1.0)'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.load(response)
        count = data.get('count')
        winrate = data.get('winrate')
        if isinstance(count, int) and isinstance(winrate, (int, float)) and count > 0:
            result = {'count': count, 'winrate': winrate}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        pass
    _cache[key] = result
    return result


_ELO = None


def _elo_table():
    """Ironclad Codex Elo cached in data/spire_codex_ironclad_cards.json (fetched once from
    /api/runs/scores/cards?character=ironclad; the API allows 15 requests/minute unkeyed)."""
    global _ELO
    if _ELO is None:
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / 'data/spire_codex_ironclad_cards.json'
        try: _ELO = json.loads(path.read_text())
        except (OSError, ValueError): _ELO = {}
    return _ELO


def elo_note(offered_card_ids, min_picks=2000):
    """Offered cards ranked by Ironclad Codex Elo: Spire Codex's less-confounded pick-strength
    rating (its raw win-rate score favours cards that merely appear in long runs)."""
    table = _elo_table(); cards = table.get('cards') or {}
    rows = [(cid, cards[cid]['elo']) for cid in offered_card_ids
            if cid in cards and cards[cid].get('elo') and (cards[cid].get('elo_picks') or 0) >= min_picks]
    if not rows: return ''
    mid = table.get('elo_median', 1520)
    def band(e): return 'strong' if e >= mid + 100 else 'above typical' if e >= mid + 30 else 'typical' if e > mid - 30 else 'below typical' if e > mid - 100 else 'weak'
    rows.sort(key=lambda r: -r[1])
    return ("Community pick strength for Ironclad (Spire Codex Elo over {:,} Ironclad runs; about {:.0f} is a typical card): ".format(table.get('ironclad_runs') or 0, mid)
            + '; '.join(f"{cid} {e:.0f} ({band(e)})" for cid, e in rows)
            + ". Use it alongside what this deck needs (see deck math); it is not a reason to skip while the deck is still mostly starter cards.")


def card_reward_note(offered_card_ids, min_samples=200, wording=1):
    """One addenda-ready line per offered card with enough community sample
    size to be meaningful, plus a closing note that skipping remains legal.
    Empty string if no card cleared the sample threshold (new/rare cards, or
    the API was unreachable this call) — callers should skip adding it then."""
    if wording >= 3: return elo_note(offered_card_ids)
    lines = []
    for card_id in offered_card_ids:
        stats = item_stats('cards', card_id)
        if stats and stats['count'] >= min_samples:
            lines.append(f"{card_id}: {stats['winrate']*100:.0f}% win rate across {stats['count']:,} community runs it appeared in")
    if not lines:
        return ''
    if wording >= 2:
        # Wording 1 told Jev that "low" rates signal a skip; nearly every card sits around 30-45%,
        # so Jev skipped ~95% of rewards from Act 1 floor 8 on (jev-ironclad-1111).
        return ("Community data (Spire Codex, win rate of community runs whose deck contained the card): "
                + '; '.join(lines) + ". Most cards fall between about 30% and 45%, so read these only "
                "relative to each other, never as low in absolute terms. Draft for the current deck first: "
                "while the deck is mostly starter Strikes/Defends (roughly under 20 cards), take the offered "
                "card that adds the most real damage, Block, draw or scaling; skip only when every option "
                "is clearly off-plan or worse than what the deck already draws.")
    return ("Community data (Spire Codex, runs where each card appeared anywhere in the deck — "
            "not deck-specific synergy): " + '; '.join(lines) + ". This is one input, not a verdict — "
            "weigh it against what the current deck actually needs. Skipping this reward is a legal, "
            "sometimes-correct choice, not a wasted turn; low win rates across all offered cards is itself "
            "a signal that skipping may be the better pick here.")
