#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


BUILDER = Path("scripts/build_dwd_annual_extremes.py")
HTML = Path("jahresextremwerte.html")


def replace_required(text: str, old: str, new: str, *, label: str) -> str:
    """Idempotenter, aber strenger Textaustausch.

    Wenn bereits der neue Text vorhanden ist, ist nichts zu tun. Fehlen alter
    und neuer Text, brechen wir ab, damit sich eine spätere Strukturänderung
    nicht unbemerkt an der Korrektur vorbeischiebt.
    """
    if old in text:
        return text.replace(old, new)
    if new in text:
        return text
    raise RuntimeError(f"Erwartete Stelle nicht gefunden: {label}")


def patch_builder() -> bool:
    text = BUILDER.read_text(encoding="utf-8")
    original = text

    replacements = [
        (
            '"label": "max. Tage >25 °C",',
            '"label": "max. Sommertage ≥25 °C",',
            "Sommertage-Label",
        ),
        (
            '"description": "Höchste Zahl der Tage mit TXK > 25,0 °C an einer Station",',
            '"description": "Höchste Zahl der Tage mit TXK >= 25,0 °C an einer Station",',
            "Sommertage-Beschreibung",
        ),
        (
            '"threshold": "TXK > 25.0",',
            '"threshold": "TXK >= 25.0",',
            "Sommertage-Schwellenmetadaten",
        ),
        (
            '"label": "max. Tage >30 °C",',
            '"label": "max. Hitzetage ≥30 °C",',
            "Hitzetage-Label",
        ),
        (
            '"description": "Höchste Zahl der Tage mit TXK > 30,0 °C an einer Station",',
            '"description": "Höchste Zahl der Tage mit TXK >= 30,0 °C an einer Station",',
            "Hitzetage-Beschreibung",
        ),
        (
            '"threshold": "TXK > 30.0",',
            '"threshold": "TXK >= 30.0",',
            "Hitzetage-Schwellenmetadaten",
        ),
        (
            "# Exakt wie in der Excel-Vorlage: strikt > 25 / > 30.",
            "# Korrekte klimatologische Definitionen: >=25 / >=30 / >=35 °C.",
            "Kenntage-Kommentar",
        ),
        (
            "if float(txk) > 25.0:",
            "if float(txk) >= 25.0:",
            "Sommertage-Berechnung",
        ),
        (
            "if float(txk) > 30.0:",
            "if float(txk) >= 30.0:",
            "Hitzetage-Berechnung",
        ),
        (
            '"Parameter: TNn, TXx, >25, >30, Tmin>20, RR24x, "',
            '"Parameter: TNn, TXx, >=25, >=30, >=35, Tropennächte, RR24x, "',
            "Konsolen-Parameterliste",
        ),
        (
            '"Kenntage werden strikt nach Excel als >25, >30 und >20 gezählt.",',
            '"Kenntage: TXK >=25,0 °C, >=30,0 °C und >=35,0 °C; Tropennächte separat nach DWD-Stundenwertdefinition.",',
            "Konsolen-Methodik",
        ),
        (
            '"Die drei Kenntage werden entsprechend der Excel-Vorlage strikt "\n            "mit TXK >25,0 °C, TXK >30,0 °C und TXK >=35,0 °C gezählt. "',
            '"Die drei temperaturbasierten Kenntage werden mit den korrekten "\n            "Schwellen TXK >=25,0 °C, TXK >=30,0 °C und TXK >=35,0 °C gezählt. "',
            "JSON-Methodennotiz",
        ),
    ]

    for old, new, label in replacements:
        text = replace_required(text, old, new, label=label)

    if text != original:
        BUILDER.write_text(text, encoding="utf-8")
        return True
    return False


def patch_html() -> bool:
    text = HTML.read_text(encoding="utf-8")
    original = text

    replacements = [
        (
            '<th class="group-days">&gt;25 °C</th>',
            '<th class="group-days">≥25 °C</th>',
            "HTML-Sommertage-Tabellenkopf",
        ),
        (
            '<th class="group-days">&gt;30 °C</th>',
            '<th class="group-days">≥30 °C</th>',
            "HTML-Hitzetage-Tabellenkopf",
        ),
        (
            "Die Kenntage entsprechen der Excel-Struktur mit den strikten Schwellen\n    TXK &gt;25,0 °C, TXK &gt;30,0 °C und TXK ≥35,0 °C.",
            "Die Kenntage verwenden die korrekten Schwellen\n    TXK ≥25,0 °C, TXK ≥30,0 °C und TXK ≥35,0 °C.",
            "HTML-Methodik",
        ),
    ]

    for old, new, label in replacements:
        text = replace_required(text, old, new, label=label)

    if text != original:
        HTML.write_text(text, encoding="utf-8")
        return True
    return False


def verify() -> None:
    builder = BUILDER.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    required_builder = [
        '"threshold": "TXK >= 25.0"',
        '"threshold": "TXK >= 30.0"',
        '"threshold": "TXK >= 35.0"',
        "if float(txk) >= 25.0:",
        "if float(txk) >= 30.0:",
        "if float(txk) >= 35.0:",
    ]
    forbidden_builder = [
        '"threshold": "TXK > 25.0"',
        '"threshold": "TXK > 30.0"',
        "if float(txk) > 25.0:",
        "if float(txk) > 30.0:",
    ]

    for needle in required_builder:
        if needle not in builder:
            raise RuntimeError(f"Builder-Prüfung fehlgeschlagen: {needle}")
    for needle in forbidden_builder:
        if needle in builder:
            raise RuntimeError(f"Alte Builder-Logik noch vorhanden: {needle}")

    for needle in ("≥25 °C", "≥30 °C", "TXK ≥25,0 °C", "TXK ≥30,0 °C"):
        if needle not in html:
            raise RuntimeError(f"HTML-Prüfung fehlgeschlagen: {needle}")


def main() -> int:
    builder_changed = patch_builder()
    html_changed = patch_html()
    verify()

    print(
        "DWD-Kenntage-Grenzwerte geprüft: "
        "Sommertage >=25,0 °C · Hitzetage >=30,0 °C · Wüstentage >=35,0 °C"
    )
    print("Builder geändert:", "ja" if builder_changed else "nein")
    print("HTML geändert:", "ja" if html_changed else "nein")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
