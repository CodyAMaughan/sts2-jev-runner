"""Local runner settings. Never execute or interpolate credential-file contents."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def typesafe_key(path=None):
    value = os.environ.get('TYPESAFE_API_KEY', '').strip()
    if value:
        return value
    path = Path(path) if path is not None else ROOT / '.env.local'
    if not path.is_file():
        return ''
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[7:].lstrip()
        name, sep, value = line.partition('=')
        if sep and name.strip() == 'TYPESAFE_API_KEY':
            value = value.strip()
            if value[:1] in ('"', "'") and value[-1:] == value[:1]:
                value = value[1:-1]
            else:
                value = value.split(' #', 1)[0].rstrip()
            return value
    return ''


def display_args(headed):
    return ['--windowed', '--resolution', '1280x720'] if headed else ['--headless']
