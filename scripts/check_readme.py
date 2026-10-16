#!/usr/bin/env python3
"""Guard for the profile README. Standard library only.

Checks: leftover placeholders, a privacy denylist (stored only as SHA-256 hashes, so this public
file does not spell the terms out; a match reports the line number, never the term), AUTO marker
integrity, committed assets referenced by the README, SVG well-formedness, <picture> completeness
and the Qunzia placement rule. With --freshness it also checks that the daily refresh really ran.
Exits 0 with a notice when README.md does not exist yet."""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

    class ZoneInfoNotFoundError(Exception):  # type: ignore[no-redef]
        pass

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / 'README.md'
LOGIN = 'Tugaytalha'

# sha256 of the lowercased, diacritic-folded term, keyed by term length
DENY = {
    5: {'ca9aac16fbb525f1ec160d985fc182bc60cdf02a0392d1c2396489f964f3496f'},
    7: {'3dabeaba7d44e61ad5d079863d0b448bcafec5212a40cf824cf0cfaffe52a190',
        '921c4d42f3111c9935928ca8fc87960050b0eaf976f627c884e05cec7a22a70f',
        'e4a2edabdfb375aab78ed646b5a726e4475e9e96381eabea5c8918f32e99f6bc',
        '59458508a0827cff5f80ed091ebd8808fbe67c97357b58ca00a278e7359dec20'},
    8: {'89717ddba1be520eed9b14a8bacfa507b79608b04b7e1b1360a18183cdab4c1d'},
    11: {'6499690df6d8d1a5322747527f9b132d34cafd3399e2ed7c9afd830f1455fe02'},
    12: {'704c7b12e644057f98735241dfba662caa711328eae3bb3d7e942f28da3ccb1a'},
}
PLACEHOLDERS = [r'\{\{', r'\bTODO\b', r'CONFIRM', r'<repository-url>', r'lorem ipsum', r'ADJUST',
                r'your-username', r'<repo-adresi>']
MARKERS = ['CONTRIB', 'YEARLY', 'COMMITTERS', 'UPDATED']
INLINE_MARKERS = {'CONTRIB', 'COMMITTERS', 'UPDATED'}  # must not start a line
RAW = re.compile(rf'raw\.githubusercontent\.com/{LOGIN}/{LOGIN}/main/([^\s"\')]+)')
errors: list[str] = []


def fail(line: int | None, msg: str) -> None:
    where = f',line={line}' if line else ''
    print(f'::error file=README.md{where}::{msg}')
    errors.append(msg)


def fold(s: str) -> str:
    s = s.replace('ı', 'i').replace('İ', 'i')
    return ''.join(c for c in unicodedata.normalize('NFKD', s.lower()) if not unicodedata.combining(c))


def check_placeholders(lines: list[str]) -> None:
    for n, line in enumerate(lines, 1):
        for pat in PLACEHOLDERS:
            if re.search(pat, line, re.I if pat == 'lorem ipsum' else 0):
                fail(n, 'unresolved placeholder')


def check_denylist(lines: list[str]) -> None:
    for n, line in enumerate(lines, 1):
        text = fold(line)
        hit = any(hashlib.sha256(text[i:i + size].encode()).hexdigest() in digests
                  for size, digests in DENY.items() for i in range(len(text) - size + 1))
        if hit:
            fail(n, 'text on this line is on the privacy denylist')


def check_qunzia(text: str, lines: list[str]) -> None:
    hits = [n for n, line in enumerate(lines, 1) if 'qunzia' in line.lower()]
    if not hits:
        return
    start = text.find('<summary><b>More projects</b></summary>')
    end = text.find('</details>', start) if start != -1 else -1
    if start == -1 or end == -1:
        fail(hits[0], 'Qunzia is mentioned but the "More projects" block was not found')
        return
    lo, hi = text.count('\n', 0, start) + 1, text.count('\n', 0, end) + 1
    if len(hits) > 1 or not lo <= hits[0] <= hi:
        fail(hits[0], 'Qunzia may appear once, inside the "More projects" block')


def check_markers(text: str, lines: list[str]) -> None:
    last = -1
    for name in MARKERS:
        starts = [m.start() for m in re.finditer(rf'<!-- AUTO:{name}:START -->', text)]
        ends = [m.start() for m in re.finditer(rf'<!-- AUTO:{name}:END -->', text)]
        if len(starts) != 1 or len(ends) != 1 or not starts[0] < ends[0]:
            fail(None, f'marker AUTO:{name} must appear exactly once as a START/END pair')
            continue
        if starts[0] < last:
            fail(None, f'marker AUTO:{name} is out of order')
        last = starts[0]
        n = text.count('\n', 0, starts[0]) + 1
        if name in INLINE_MARKERS and lines[n - 1].lstrip().startswith('<!-- AUTO:'):
            fail(n, f'inline marker AUTO:{name} must not start a line (it would become an HTML block)')


def check_assets(text: str) -> None:
    for m in RAW.finditer(text):
        rel = m.group(1)
        if not (ROOT / rel).is_file():
            fail(text.count('\n', 0, m.start()) + 1, f'referenced asset is missing: {rel}')


def check_svgs() -> None:
    for folder in ('assets', 'profile-3d-contrib'):
        for path in (ROOT / folder).rglob('*.svg'):
            try:
                ET.parse(path)
            except ET.ParseError as exc:
                fail(None, f'{path.relative_to(ROOT).as_posix()} is not well-formed: {exc}')


def check_pictures(text: str) -> None:
    for m in re.finditer(r'<picture>(.*?)</picture>', text, re.S):
        block, n = m.group(1), text.count('\n', 0, m.start()) + 1
        if 'prefers-color-scheme: dark' not in block or 'prefers-color-scheme: light' not in block:
            fail(n, '<picture> needs both a dark and a light <source>')
        alt = re.search(r'<img[^>]*\salt="([^"]*)"', block)
        if not alt or not alt.group(1).strip():
            fail(n, '<picture> needs a non-empty alt text')


def istanbul_today() -> date:
    try:
        tz = ZoneInfo('Europe/Istanbul') if ZoneInfo else timezone(timedelta(hours=3))
    except (ZoneInfoNotFoundError, KeyError):
        tz = timezone(timedelta(hours=3))
    return datetime.now(tz).date()


def check_freshness(text: str) -> None:
    today = istanbul_today()
    m = re.search(r'<!-- AUTO:UPDATED:START -->(.*?)<!-- AUTO:UPDATED:END -->', text, re.S)
    try:
        updated = datetime.strptime(m.group(1).strip(), '%d %b %Y').date() if m else None
    except ValueError:
        updated = None
    if not updated or (today - updated).days > 3:
        fail(None, f'"Last refresh" is stale or unreadable ({m.group(1).strip() if m else "missing"}); '
                   'the daily workflow may have stopped')
    puzzle = ROOT / 'assets' / 'generated' / 'puzzle-light.svg'
    t = re.search(r'solved for \w+ (\d+) (\w+) (\d{4})', puzzle.read_text(encoding='utf-8')) if puzzle.exists() else None
    try:
        solved = datetime.strptime(' '.join(t.groups()), '%d %B %Y').date() if t else None
    except ValueError:
        solved = None
    if not solved or (today - solved).days > 2:
        fail(None, 'the puzzle image is more than 2 days old or unreadable')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--freshness', action='store_true', help='also check that the daily refresh ran')
    args = ap.parse_args()
    if not README.exists():
        print('::notice::README.md not found yet; nothing to check.')
        return 0
    text = README.read_text(encoding='utf-8')
    lines = text.split('\n')
    check_placeholders(lines)
    check_denylist(lines)
    check_qunzia(text, lines)
    check_markers(text, lines)
    check_assets(text)
    check_svgs()
    check_pictures(text)
    if args.freshness:
        check_freshness(text)
    print('README guard: ' + ('FAILED' if errors else 'all checks passed'))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
