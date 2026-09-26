import sys,unittest
from pathlib import Path
from unittest.mock import patch
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import spire_codex

class FakeResponse:
    def __init__(self,payload):self.payload=payload
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self):import json;return json.dumps(self.payload).encode()

class SpireCodex(unittest.TestCase):
    def setUp(self):spire_codex._cache.clear()

    def test_populated_result_cached_and_returned(self):
        with patch('urllib.request.urlopen',return_value=FakeResponse({'count':45924,'winrate':0.3131})) as urlopen:
            first=spire_codex.item_stats('cards','IRON_WAVE')
            second=spire_codex.item_stats('cards','IRON_WAVE')
        self.assertEqual(first,{'count':45924,'winrate':0.3131})
        self.assertEqual(second,first)
        urlopen.assert_called_once()  # second call served from cache, no repeat request

    def test_empty_partners_response_is_none(self):
        with patch('urllib.request.urlopen',return_value=FakeResponse({'kind':'cards','item_id':'BASH','partners':{}})):
            self.assertIsNone(spire_codex.item_stats('cards','BASH'))

    def test_network_failure_is_none_not_raised(self):
        with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('timed out')):
            self.assertIsNone(spire_codex.item_stats('cards','IRON_WAVE'))

    def test_card_reward_note_formats_and_mentions_skip(self):
        def fake(item_type,item_id,timeout=3):
            return {'IRON_WAVE':{'count':45924,'winrate':0.3131},'ARMAMENTS':{'count':100,'winrate':0.4}}.get(item_id)
        with patch('spire_codex.item_stats',side_effect=fake):
            note=spire_codex.card_reward_note(['IRON_WAVE','ARMAMENTS','UNKNOWN_CARD'],min_samples=200)
        self.assertIn('IRON_WAVE',note);self.assertIn('31%',note);self.assertIn('45,924',note)
        self.assertNotIn('ARMAMENTS',note)  # below min_samples threshold
        self.assertIn('Skipping this reward is a legal',note)

    def test_card_reward_note_empty_when_nothing_clears_threshold(self):
        with patch('spire_codex.item_stats',return_value=None):
            self.assertEqual(spire_codex.card_reward_note(['X','Y']),'')

if __name__=='__main__':unittest.main()
