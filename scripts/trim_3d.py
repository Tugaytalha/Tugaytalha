#!/usr/bin/env python3
"""Remove the public-only star/fork counters and the language pie from the 3D contribution SVGs.

Written for the output of yoshi389111/github-profile-3d-contrib v0.9.3 (type "normal"). It expects
exactly: one pie group (<g transform="translate(40, 520)">), two icon groups (scale(2)) and two
titled text nodes (star and fork counts) inside the last un-transformed top-level <g>.
If the structure is anything else the file is NOT written: yesterday's committed version is restored
(or the file is removed on the very first run) and the script exits 1, so an untrimmed image
with the small public numbers never gets committed. Standard library only."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [ROOT / 'profile-3d-contrib' / 'profile-3d-dark.svg', ROOT / 'profile-3d-contrib' / 'profile-3d-light.svg']
SVG_NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', SVG_NS)
PIE = re.compile(r'translate\(\s*40\s*,\s*520\s*\)')
ICON = re.compile(r'scale\(\s*2\s*\)')


def tag(el: ET.Element) -> str:
    return el.tag.split('}', 1)[-1]


def trim(path: Path) -> None:
    root = ET.parse(path).getroot()
    top = list(root)

    pies = [el for el in top if tag(el) == 'g' and PIE.search(el.get('transform', ''))]
    plain_groups = [el for el in top if tag(el) == 'g' and not el.get('transform')]
    if len(pies) != 1 or not plain_groups:
        raise ValueError(f'pie groups={len(pies)}, plain groups={len(plain_groups)}')
    last = plain_groups[-1]
    icons = [el for el in last if tag(el) == 'g' and ICON.search(el.get('transform', ''))]
    counters = [el for el in last if tag(el) == 'text' and any(tag(c) == 'title' for c in el)]
    if len(icons) != 2 or len(counters) != 2:
        raise ValueError(f'icons={len(icons)}, counters={len(counters)}')

    root.remove(pies[0])
    for el in icons + counters:
        last.remove(el)

    data = ET.tostring(root, encoding='unicode')
    ET.fromstring(data)  # must still be well-formed
    if 'M8 .25a' in data or 'M5 3.25a' in data:
        raise ValueError('star/fork icon paths still present')
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(data + '\n')
    os.replace(tmp, path)


def restore(path: Path) -> None:
    """Put yesterday's committed file back, or delete the untrimmed one when there is none."""
    rel = path.relative_to(ROOT).as_posix()
    done = subprocess.run(['git', 'checkout', 'HEAD', '--', rel], cwd=ROOT, capture_output=True)
    if done.returncode != 0 and path.exists():
        path.unlink()


def main() -> int:
    failed = 0
    for path in FILES:
        if not path.exists():
            print(f'::warning::{path.name} not found; nothing to trim.')
            failed += 1
            continue
        try:
            trim(path)
            print(f'trimmed {path.name}')
        except Exception as exc:
            print(f'::warning::could not trim {path.name} ({type(exc).__name__}: {exc}); '
                  'restoring the previous version.')
            restore(path)
            failed += 1
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
