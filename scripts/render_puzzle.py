#!/usr/bin/env python3
"""Render today's wooden-calendar puzzle, solved by Tugaytalha/Wooden-Calendar-Puzzle-Solver,
as dark and light SVGs for the profile README. Standard library only.

If anything goes wrong the previous images are kept and the script exits 0 (the workflow's
failure step reports problems through the step outcome, not through this exit code)."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

    class ZoneInfoNotFoundError(Exception):  # type: ignore[no-redef]
        pass

CELL, GAP, PAD, CAPTION = 44, 4, 20, 46
STEP = CELL + GAP
MONO = 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'
# The solver uses ASCII labels; show proper Turkish letters.
DISPLAY = {'SUB': 'ŞUB', 'NIS': 'NİS', 'AGU': 'AĞU', 'EKI': 'EKİ', 'CAR': 'ÇAR'}
THEMES = {
    'dark': {
        'panel': '#0B1020', 'edge': '#1E293B', 'text': '#E2E8F0', 'muted': '#94A3B8',
        'pieces': ['#8B5CF6', '#22D3EE', '#F472B6', '#34D399', '#FBBF24',
                   '#60A5FA', '#C084FC', '#2DD4BF', '#FB7185', '#818CF8'],
    },
    'light': {
        'panel': '#F8FAFC', 'edge': '#E2E8F0', 'text': '#0F172A', 'muted': '#475569',
        'pieces': ['#7C3AED', '#0891B2', '#DB2777', '#059669', '#D97706',
                   '#2563EB', '#9333EA', '#0D9488', '#E11D48', '#4F46E5'],
    },
}


def fmt_date(d: date, weekday: bool = False) -> str:
    base = f'{d.day} {d:%b %Y}'
    return f'{d:%a} {base}' if weekday else base


def render(board, labels, theme: str, day: date, solve_ms: float) -> str:
    t = THEMES[theme]
    rows, cols = len(board), len(board[0])
    w = 2 * PAD + cols * STEP - GAP
    h_board = 2 * PAD + rows * STEP - GAP
    h = h_board + CAPTION
    out = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}' role='img'>",
        f"<title>Wooden calendar puzzle, solved for {day:%A} {day.day} {day:%B %Y}</title>",
        f"<rect width='{w}' height='{h}' rx='16' fill='{t['panel']}' stroke='{t['edge']}'/>",
    ]

    def same(r: int, c: int, v: int) -> bool:
        return 0 <= r < rows and 0 <= c < cols and board[r][c] == v

    for r in range(rows):
        for c in range(cols):
            v = board[r][c]
            x, y = PAD + c * STEP, PAD + r * STEP
            if v > 0:
                fill = t['pieces'][(v - 1) % len(t['pieces'])]
                parts = [(x, y, CELL, CELL)]
                if same(r, c + 1, v):
                    parts.append((x + CELL - 8, y, GAP + 16, CELL))
                if same(r + 1, c, v):
                    parts.append((x, y + CELL - 8, CELL, GAP + 16))
                if same(r, c + 1, v) and same(r + 1, c, v) and same(r + 1, c + 1, v):
                    parts.append((x + CELL - 8, y + CELL - 8, GAP + 16, GAP + 16))
                for i, (px, py, pw, ph) in enumerate(parts):
                    rounded = " rx='7'" if i == 0 else ''
                    out.append(f"<rect x='{px}' y='{py}' width='{pw}' height='{ph}'{rounded} fill='{fill}'/>")
            elif v == -1:
                label = DISPLAY.get(labels[r][c], labels[r][c])
                out.append(
                    f"<rect x='{x + 1}' y='{y + 1}' width='{CELL - 2}' height='{CELL - 2}' rx='7' fill='none' "
                    f"stroke='{t['text']}' stroke-width='2' stroke-dasharray='5 3'/>"
                )
                out.append(
                    f"<text x='{x + CELL / 2}' y='{y + CELL / 2 + 5}' text-anchor='middle' font-family='{MONO}' "
                    f"font-size='14' font-weight='700' fill='{t['text']}'>{escape(label)}</text>"
                )
    caption = f'{fmt_date(day, weekday=True)} · solved in {solve_ms:.0f} ms'
    out.append(
        f"<text x='{w / 2}' y='{h_board + 18}' text-anchor='middle' font-family='{MONO}' "
        f"font-size='14' fill='{t['muted']}'>{escape(caption)}</text>"
    )
    out.append('</svg>')
    return '\n'.join(out) + '\n'


def local_today(tz_name: str) -> date:
    try:
        tz = ZoneInfo(tz_name) if ZoneInfo else timezone(timedelta(hours=3))
    except (ZoneInfoNotFoundError, KeyError):  # Windows without tzdata; Turkey is UTC+3 all year
        tz = timezone(timedelta(hours=3))
    return datetime.now(tz).date()


def write_atomic(path: Path, text: str) -> None:
    ET.fromstring(text)  # raises if the SVG is not well-formed; nothing is written then
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--solver', type=Path, required=True, help='checkout of Wooden-Calendar-Puzzle-Solver')
    ap.add_argument('--out', type=Path, required=True, help='output directory for puzzle-{dark,light}.svg')
    ap.add_argument('--tz', default='Europe/Istanbul')
    ap.add_argument('--date', help='YYYY-MM-DD (testing); default is today in --tz')
    args = ap.parse_args()

    try:
        sys.path.insert(0, str(args.solver.resolve()))
        from fast_dp_solver import FastCalendarPuzzleSolver

        today = date.fromisoformat(args.date) if args.date else local_today(args.tz)
        solver = FastCalendarPuzzleSolver()
        started = time.perf_counter()
        boards = solver.solve_for_date(today.day, today.month, today.isoweekday())
        solve_ms = (time.perf_counter() - started) * 1000
        if not boards:
            print(f'::warning::No solution for {today}; keeping the previous images.')
            return 0
        args.out.mkdir(parents=True, exist_ok=True)
        rendered = {theme: render(boards[0], solver.BOARD, theme, today, solve_ms) for theme in THEMES}
        for theme, svg in rendered.items():
            write_atomic(args.out / f'puzzle-{theme}.svg', svg)
    except Exception as exc:  # keep yesterday's images
        print(f'::warning::render_puzzle failed ({type(exc).__name__}: {exc}); keeping the previous images.')
        return 0
    print(f'{fmt_date(today)}: solved in {solve_ms:.0f} ms')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
