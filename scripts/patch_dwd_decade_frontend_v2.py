#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

OLD_OPTIONS = '''        <option value="txk_high">Tmax · höchstes Maximum</option>
        <option value="tnk_low">Tmin · tiefstes Minimum</option>'''

NEW_OPTIONS = '''        <option value="txk_high">Tmax · höchstes Maximum</option>
        <option value="txk_low">Tmax · niedrigstes Maximum</option>
        <option value="tnk_high">Tmin · höchstes Minimum</option>
        <option value="tnk_low">Tmin · tiefstes Minimum</option>'''

OLD_METHOD = '''    Stationen. Für jede meteorologische Dekade wird pro Station der höchste Tmax- bzw.
    niedrigste Tmin-Wert bestimmt. Rangliste und Karte verwenden je Station deren
    persönlichen Dekadenrekord.'''

NEW_METHOD = '''    Stationen. Für jede meteorologische Dekade werden pro Station höchstes und
    niedrigstes Tmax sowie höchstes und niedrigstes Tmin bestimmt. Rangliste und Karte
    verwenden je Station deren persönlichen Dekadenrekord.'''

OLD_COLOR = '    els.recordValue.className = `summary-value ${metric === "txk_high" ? "hot" : "cold"}`;'
NEW_COLOR = '    els.recordValue.className = `summary-value ${metric.endsWith("_high") ? "hot" : "cold"}`;'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: genau 1 Treffer erwartet, gefunden: {count}")
    return text.replace(old, new, 1)


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    if '<option value="txk_low">' not in text:
        text = replace_once(text, OLD_OPTIONS, NEW_OPTIONS, "Parameterauswahl")

    if "niedrigstes Tmax sowie höchstes und niedrigstes Tmin" not in text:
        text = replace_once(text, OLD_METHOD, NEW_METHOD, "Methodiktext")

    if 'metric.endsWith("_high")' not in text:
        text = replace_once(text, OLD_COLOR, NEW_COLOR, "Rekordfarbe")

    required = (
        '<option value="txk_high">',
        '<option value="txk_low">',
        '<option value="tnk_high">',
        '<option value="tnk_low">',
        'metric.endsWith("_high")',
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError("Frontend-Prüfung fehlgeschlagen: " + ", ".join(missing))

    if text != original:
        path.write_text(text, encoding="utf-8")
        print("dekadenrekorde.html auf vier Temperaturparameter erweitert.")
        return True

    print("Vier Temperaturparameter sind bereits vorhanden.")
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="dekadenrekorde.html")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"Datei nicht gefunden: {path}")

    patch(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
