#!/usr/bin/env python3
from pathlib import Path

SCRIPT_TAG='<script src="monthly_frequency.js?v=1"></script>'

def patch_file(target: Path) -> bool:
    text=target.read_text(encoding='utf-8')
    if SCRIPT_TAG in text:
        return False
    if '</body>' not in text:
        raise RuntimeError('index.html enthält kein </body>.')
    text=text.replace('</body>',f'{SCRIPT_TAG}\n</body>',1)
    target.write_text(text,encoding='utf-8')
    return True

def main() -> int:
    root=Path(__file__).resolve().parents[1]
    changed=patch_file(root/'index.html')
    print('Häufigkeitsverteilung eingebunden.' if changed else 'Häufigkeitsverteilung bereits eingebunden.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
