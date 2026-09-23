"""A successful encoder exit alone does not establish a complete game recording."""
import json, subprocess
from pathlib import Path

def classify_duration(duration, expected):
    tolerance=max(5.0, expected*.05)
    return 'complete' if duration>0 and duration+tolerance>=expected else 'incomplete'

def validate(directory, exit_code):
    directory=Path(directory)
    result={'path':'game.mp4','exit_code':exit_code,'audio':False,'status':'failed'}
    if exit_code!=0:return result
    try:
        expected=max(0,(directory/'recording.stop').stat().st_mtime-(directory/'game.mp4.ready').stat().st_mtime)
        raw=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(directory/'game.mp4')],capture_output=True,text=True,check=True,timeout=15)
        duration=float(json.loads(raw.stdout)['format']['duration'])
        result.update(status=classify_duration(duration,expected),duration_seconds=duration,expected_capture_seconds=round(expected,3))
        if result['status']!='complete':result['reason']='Video duration is shorter than the capture interval; successful encoder exit was insufficient.'
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as error:
        result.update(status='unverified',reason='Could not verify recording duration: '+type(error).__name__)
    return result
