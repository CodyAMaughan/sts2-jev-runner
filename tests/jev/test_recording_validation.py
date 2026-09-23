import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from recording_validation import classify_duration
class RecordingValidationTests(unittest.TestCase):
    def test_successful_but_stalled_capture_is_incomplete(self):
        self.assertEqual(classify_duration(3.75,184.5),'incomplete')
    def test_full_capture_accepts_small_shutdown_gap(self):
        self.assertEqual(classify_duration(182,184.5),'complete')
    def test_empty_recording_never_complete(self):
        self.assertEqual(classify_duration(0,0),'incomplete')
