import sys,unittest
from pathlib import Path
from unittest.mock import patch
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from jev_playtest import request

def http_error(code):return urllib.error.HTTPError('http://x',code,'err',{},None)

class FakeResponse:
    def __init__(self,payload):self.payload=payload
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self):import json;return json.dumps(self.payload).encode()

class Retry(unittest.TestCase):
    def test_retryable_5xx_then_success(self):
        calls=[http_error(520),http_error(502),FakeResponse({'ok':True})]
        def fake_urlopen(req,timeout=None):
            result=calls.pop(0)
            if isinstance(result,Exception):raise result
            return result
        with patch('urllib.request.urlopen',side_effect=fake_urlopen),patch('time.sleep') as sleep:
            self.assertEqual(request('http://x','tok',{'a':1},backoff=1),{'ok':True})
        self.assertEqual(sleep.call_count,2)

    def test_non_retryable_4xx_raises_immediately(self):
        with patch('urllib.request.urlopen',side_effect=http_error(422)),patch('time.sleep') as sleep:
            with self.assertRaises(urllib.error.HTTPError) as caught:request('http://x','tok',{})
        self.assertEqual(caught.exception.code,422);sleep.assert_not_called()

    def test_exhausts_retries_and_raises(self):
        with patch('urllib.request.urlopen',side_effect=http_error(520)),patch('time.sleep') as sleep:
            with self.assertRaises(urllib.error.HTTPError):request('http://x','tok',{},retries=3,backoff=1)
        self.assertEqual(sleep.call_count,2)

    def test_retries_1_means_no_internal_retry(self):
        with patch('urllib.request.urlopen',side_effect=http_error(520)),patch('time.sleep') as sleep:
            with self.assertRaises(urllib.error.HTTPError):request('http://x','tok',{},retries=1)
        sleep.assert_not_called()

    def test_connection_error_retried(self):
        calls=[ConnectionError('refused'),FakeResponse({'ok':True})]
        def fake_urlopen(req,timeout=None):
            result=calls.pop(0)
            if isinstance(result,Exception):raise result
            return result
        with patch('urllib.request.urlopen',side_effect=fake_urlopen),patch('time.sleep') as sleep:
            self.assertEqual(request('http://x','tok',{},backoff=1),{'ok':True})
        sleep.assert_called_once()

if __name__=='__main__':unittest.main()
