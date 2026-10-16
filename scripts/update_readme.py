#!/usr/bin/env python3
"""Refresh the auto-generated blocks of README.md. Standard library only.

Blocks (between <!-- AUTO:NAME:START --> and <!-- AUTO:NAME:END -->):
  CONTRIB    inline text in the [!NOTE]: this year's contribution total and private share
  YEARLY     table of contributions per year (totals only)
  COMMITTERS committers.top Turkiye and worldwide rank badges, each shown only while ranked
  UPDATED    date of the last successful refresh

Numbers are only accepted when they pass sanity guards (see check_year). A block that cannot be
refreshed keeps its old text and a ::warning:: is printed; the script exits 1 only for structural
problems (missing or duplicated marker)."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
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
STATS = ROOT / 'data' / 'stats.json'
LOGIN = os.environ.get('PROFILE_LOGIN', 'Tugaytalha')
FIRST_YEAR = 2024
RAW = f'https://raw.githubusercontent.com/{LOGIN}/{LOGIN}/main'
UA = f'{LOGIN}-profile-readme'
# committers.top lists (public + private contributions): (preset, local file stem, phrase for the alt text)
COMMITTERS_BADGES = [
    ('turkey_private', 'committers-turkey', 'in Türkiye'),
    ('worldwide_private', 'committers-worldwide', 'worldwide'),
]

QUERY = """query($login: String!, $from: DateTime!, $to: DateTime!) { user(login: $login) {
  contributionsCollection(from: $from, to: $to) {
    restrictedContributionsCount
    totalCommitContributions totalIssueContributions totalPullRequestContributions
    totalPullRequestReviewContributions totalRepositoryContributions
    contributionCalendar { totalContributions } } } }"""


def warn(msg: str) -> None:
    print(f'::warning::{msg}')


def local_now(tz_name: str = 'Europe/Istanbul') -> datetime:
    try:
        tz = ZoneInfo(tz_name) if ZoneInfo else timezone(timedelta(hours=3))
    except (ZoneInfoNotFoundError, KeyError):  # Turkey is UTC+3 all year
        tz = timezone(timedelta(hours=3))
    return datetime.now(tz)


def fmt_day(d: date, year: bool = False) -> str:
    return f'{d.day} {d:%b %Y}' if year else f'{d.day} {d:%b}'


# ---------------------------------------------------------------- GitHub access
def gql(query: str, **variables):
    token = os.environ.get('GH_READ_TOKEN')
    if token:
        body = json.dumps({'query': query, 'variables': variables}).encode()
        req = urllib.request.Request(
            'https://api.github.com/graphql', data=body,
            headers={'Authorization': f'Bearer {token}', 'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    elif shutil.which('gh'):  # local testing: let gh handle the credentials
        cmd = ['gh', 'api', 'graphql', '-f', f'query={query}']
        for key, value in variables.items():
            cmd += ['-f', f'{key}={value}']
        data = json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True).stdout)
    else:
        raise RuntimeError('no GH_READ_TOKEN and no gh CLI available')
    if data.get('errors'):
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data['data']


def fetch_year(year: int, now: datetime) -> dict:
    end = now.astimezone(timezone.utc) if year == now.year else datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    c = gql(QUERY, login=LOGIN, **{'from': f'{year}-01-01T00:00:00Z',
                                   'to': end.strftime('%Y-%m-%dT%H:%M:%SZ')})['user']['contributionsCollection']
    parts = [c['totalCommitContributions'], c['totalIssueContributions'], c['totalPullRequestContributions'],
             c['totalPullRequestReviewContributions'], c['totalRepositoryContributions']]
    return {'total': c['contributionCalendar']['totalContributions'],
            'restricted': c['restrictedContributionsCount'], 'parts': parts}


def check_year(year: int, new: dict, old: dict | None) -> str | None:
    """Return None when the numbers are trustworthy, otherwise the reason they are not."""
    values = [new['total'], new['restricted'], *new['parts']]
    if not all(isinstance(v, int) and v >= 0 for v in values):
        return 'non-integer or negative value'
    if new['total'] != sum(new['parts']) + new['restricted']:
        return f"invariant failed: {new['total']} != {sum(new['parts'])} + {new['restricted']}"
    if old:
        if new['restricted'] == 0 and old.get('restricted', 0) > 0:
            return 'restricted count dropped to 0 (private contribution sharing off, or token cannot see it)'
        if old.get('total', 0) and new['total'] < 0.9 * old['total']:
            return f"total dropped more than 10% ({old['total']} -> {new['total']})"
    return None


# ---------------------------------------------------------------- block rendering
def replace_block(text: str, name: str, body: str, inline: bool) -> str:
    pattern = re.compile(rf'(<!-- AUTO:{name}:START -->).*?(<!-- AUTO:{name}:END -->)', re.S)
    found = pattern.findall(text)
    if len(found) != 1:
        raise SystemExit(f'::error::marker AUTO:{name} must appear exactly once (found {len(found)})')
    pad = '' if inline else '\n\n'
    return pattern.sub(lambda m: f'{m.group(1)}{pad}{body}{pad}{m.group(2)}', text, count=1)


def contrib_text(years: dict, now: datetime) -> str:
    cur, prev = years.get(str(now.year)), years.get(str(now.year - 1))
    doy = now.timetuple().tm_yday
    use, label = (cur, f'In {now.year} so far') if cur else (None, '')
    if (doy < 32 or (cur and cur['total'] < 50)) and prev:
        use, label = prev, f'In {now.year - 1}'
    if not use or not use['total']:
        raise RuntimeError('no usable year for the NOTE')
    pct = round(100 * use['restricted'] / use['total'])
    return f"{label}: **{use['total']:,}** contributions, **{pct}%** of them in private repositories."


def yearly_table(years: dict, now: datetime) -> str:
    rows = ['| Year | Contributions |', '| :-- | --: |']
    for year in range(now.year, FIRST_YEAR - 1, -1):
        y = years.get(str(year))
        if not y:
            continue
        label = f'{year} (to {fmt_day(now.date())})' if year == now.year else str(year)
        rows.append(f"| {label} | {y['total']:,} |")
    return '\n'.join(rows)


def fetch_committers_badge(preset: str) -> tuple[str, int | None]:
    """(svg, rank) for one committers.top list; rank is None while unranked. Raises on anything unexpected
    (the service answers 200 even for unknown users, so the label is what we trust, not the status)."""
    req = urllib.request.Request(f'https://user-badge.committers.top/{preset}/{LOGIN}.svg', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        svg = resp.read().decode('utf-8', 'replace')
    label = re.search(r'aria-label="([^"]*)"', svg) or re.search(r'<title>([^<]*)</title>', svg)
    label = label.group(1) if label else ''
    if 'committers.top' not in label.lower():
        raise RuntimeError(f'unexpected {preset} badge label: {label!r}')
    if 'unranked' in label.lower():
        return svg, None
    m = re.search(r'#\s*(\d+)', label)
    if not m:
        raise RuntimeError(f'cannot read rank from {preset} label: {label!r}')
    return svg, int(m.group(1))


def committers_block(write: bool = True) -> tuple[str, list[str]]:
    """(block text, status lines). A badge appears only for lists where the account is ranked, so an
    'unranked' badge is never shown. If any fetch fails the caller keeps yesterday's block."""
    badges, status = [], []
    for preset, stem, where in COMMITTERS_BADGES:
        svg, rank = fetch_committers_badge(preset)
        if rank is None:
            status.append(f'{preset}: unranked (hidden)')
            continue
        status.append(f'{preset}: #{rank} (shown)')
        if write:
            path = ROOT / 'assets' / 'generated' / f'{stem}.svg'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(svg, encoding='utf-8', newline='\n')
        alt = f'committers.top: #{rank} {where} (public and private contributions)'
        badges.append(f'<a href="https://committers.top/{preset}"><img height="20" alt="{alt}" '
                      f'src="{RAW}/assets/generated/{stem}.svg"></a>')
    return ' '.join(badges), status


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true', help='print the blocks, write nothing')
    ap.add_argument('--today', help='YYYY-MM-DD override for tests')
    args = ap.parse_args()

    if not README.exists():
        print('::notice::README.md not found yet; nothing to refresh.')
        return 0
    now = local_now()
    if args.today:
        d = date.fromisoformat(args.today)
        now = now.replace(year=d.year, month=d.month, day=d.day)

    stored = json.loads(STATS.read_text(encoding='utf-8')) if STATS.exists() else {'years': {}}
    years = dict(stored.get('years', {}))
    changed_years, stats_ok = False, True
    token_source = os.environ.get('TOKEN_SOURCE', 'gh CLI / local')
    print(f'token source: {token_source}')
    for year in range(FIRST_YEAR, now.year + 1):
        try:
            new = fetch_year(year, now)
            problem = check_year(year, new, years.get(str(year)))
        except Exception as exc:  # network, API, auth
            problem, new = f'{type(exc).__name__}: {exc}', None
        if problem:
            warn(f'{year}: keeping stored numbers ({problem})')
            if year == now.year:
                stats_ok = False
            continue
        print(f"{year}: total={new['total']} restricted={new['restricted']}")
        years[str(year)] = {'total': new['total'], 'restricted': new['restricted']}
        changed_years = True

    text = original = README.read_text(encoding='utf-8')
    refreshed = []
    try:
        if str(now.year) in years:
            text = replace_block(text, 'CONTRIB', contrib_text(years, now), inline=True)
            text = replace_block(text, 'YEARLY', yearly_table(years, now), inline=False)
            refreshed.append('numbers')
    except RuntimeError as exc:
        warn(f'CONTRIB/YEARLY not refreshed: {exc}')
        stats_ok = False
    try:
        body, status = committers_block(write=not args.dry_run)
        text = replace_block(text, 'COMMITTERS', body, inline=True)
        print('committers.top: ' + '; '.join(status))
    except Exception as exc:
        warn(f'COMMITTERS left unchanged: {exc}')
    if stats_ok and 'numbers' in refreshed:
        text = replace_block(text, 'UPDATED', fmt_day(now.date(), year=True), inline=True)

    if args.dry_run:
        for name in ('CONTRIB', 'YEARLY', 'COMMITTERS', 'UPDATED'):
            m = re.search(rf'<!-- AUTO:{name}:START -->(.*?)<!-- AUTO:{name}:END -->', text, re.S)
            print(f'--- {name} ---\n{m.group(1).strip() if m else "(marker missing)"}')
        return 0
    if text != original:
        fd, tmp = tempfile.mkstemp(dir=ROOT, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(tmp, README)
    if changed_years:
        STATS.parent.mkdir(exist_ok=True)
        stored['years'] = years
        STATS.write_text(json.dumps(stored, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
