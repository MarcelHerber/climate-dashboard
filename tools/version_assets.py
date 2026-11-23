#!/usr/bin/env python3
"""version_assets.py – automatische Cache-Versionierung für das Klima-Dashboard (Schritt 4).

Ersetzt alle ?v=-Versionen durch einen Hash des Dateiinhalts (SHA-256, erste 10 Zeichen):

  1. <script src="…">- und <link href="…">-Tags lokaler .js/.css-Dateien in den HTML-Dateien
  2. die Modultabelle im Lader (js/loader.js:  "name":["pfad.js","version"])
  3. Dateiverweise in JS-Zeichenketten, z. B. 'era5_stratosphere.js?v=1' in era5_europe.js

Verweist eine Datei auf eine andere, wird zuerst die referenzierte Datei gehasht und danach die
verweisende (ihr Inhalt enthält ja die neue Version). Ändert sich eine Datei, ändern sich daher
automatisch auch alle Dateien, die auf sie verweisen (z. B. loader.js und die index.html).

Nur Python-Standardbibliothek. Beispiele:

  python tools/version_assets.py                       # Versionen schreiben
  python tools/version_assets.py --check               # nur prüfen (Exit-Code 1, wenn veraltet)
  python tools/version_assets.py --manifest asset-manifest.json
  python tools/version_assets.py --copy-to _site       # kopiert genau die Dateien, die die Seite braucht
  python tools/version_assets.py --verify-dir _site    # prüft, ob alle Dateien im Build vorhanden
                                                       # und aktuell sind (hätte den 404 bei
                                                       # era5_stratosphere.js gefunden)

Exit-Codes: 0 = ok, 1 = veraltete Versionen (--check) bzw. Verifikation fehlgeschlagen,
            2 = Verweis auf eine fehlende Datei (außer mit --allow-missing) oder Zyklus.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

HASH_LENGTH = 10
LOCAL_EXTENSIONS = (".js", ".css")

# <script … src="X"> und <link … href="X">
HTML_REF = re.compile(r'(<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*")([^"]+)(")', re.IGNORECASE)
# 'datei.js?v=…' als Zeichenkette in JS
JS_REF = re.compile(r'''(["'`])([A-Za-z0-9_./-]+\.(?:js|css))\?v=([^"'`&\s]*)\1''')
# Modultabelle im Lader: ["pfad.js","version"]
TABLE_REF = re.compile(r'\["([A-Za-z0-9_./-]+\.js)","([^"]*)"\]')


class AssetError(Exception):
    pass


def digest(text_or_bytes):
    data = text_or_bytes.encode("utf-8") if isinstance(text_or_bytes, str) else text_or_bytes
    data = data.replace(b"\r\n", b"\n")  # gleicher Hash unter Windows und Linux
    return hashlib.sha256(data).hexdigest()[:HASH_LENGTH]


def is_local_asset(url):
    if url.startswith(("http://", "https://", "//", "data:", "/", "#", "mailto:")):
        return False
    return url.split("?", 1)[0].lower().endswith(LOCAL_EXTENSIONS)


def normalize(url_path):
    return url_path[2:] if url_path.startswith("./") else url_path


class Versioner:
    def __init__(self, root, loader):
        self.root = Path(root)
        self.loader = loader
        self.done = {}      # rel -> (neuer_text, hash)
        self.original = {}  # rel -> alter_text
        self.referenced_by = {}
        self.missing = []
        self.warnings = []

    def _read(self, rel):
        path = self.root / rel
        if not path.is_file():
            return None
        with path.open(encoding="utf-8", newline="") as handle:  # Zeilenenden unverändert lassen
            return handle.read()

    def process(self, rel, stack=()):
        """Liefert (text, hash) einer Datei, nachdem alle ihre Verweise aktualisiert wurden."""
        if rel in self.done:
            return self.done[rel]
        if rel in stack:
            raise AssetError("Zyklus: " + " -> ".join(stack + (rel,)))
        text = self._read(rel)
        if text is None:
            raise AssetError("Datei fehlt: " + rel)
        self.original[rel] = text
        new_text = text
        if rel.endswith(".js"):
            def js_sub(match):
                quote, child, _old = match.groups()
                version = self._child_hash(child, rel, stack + (rel,))
                return match.group(0) if version is None else f"{quote}{child}?v={version}{quote}"
            new_text = JS_REF.sub(js_sub, new_text)
            if rel == self.loader:
                def table_sub(match):
                    child, _old = match.groups()
                    version = self._child_hash(child, rel, stack + (rel,))
                    return match.group(0) if version is None else f'["{child}","{version}"]'
                new_text = TABLE_REF.sub(table_sub, new_text)
        result = (new_text, digest(new_text))
        self.done[rel] = result
        return result

    def _child_hash(self, child, parent, stack):
        child = normalize(child)
        if not (self.root / child).is_file():
            self.missing.append((parent, child))
            return None
        self.referenced_by.setdefault(child, set()).add(parent)
        return self.process(child, stack)[1]

    def process_html(self, rel):
        text = self._read(rel)
        if text is None:
            raise AssetError("HTML-Datei fehlt: " + rel)
        self.original[rel] = text

        def html_sub(match):
            pre, url, post = match.groups()
            if not is_local_asset(url):
                return match.group(0)
            path, _, query = url.partition("?")
            path = normalize(path)
            if query and not (query.startswith("v=") and "&" not in query):
                self.warnings.append(f"{rel}: {url} hat eine andere Query – übersprungen")
                return match.group(0)
            version = self._child_hash(path, rel, ())
            return match.group(0) if version is None else f"{pre}{path}?v={version}{post}"

        new_text = HTML_REF.sub(html_sub, text)
        self.done[rel] = (new_text, None)
        return new_text


def main():
    parser = argparse.ArgumentParser(description="Cache-Versionierung per Inhalts-Hash")
    parser.add_argument("--root", default=".", help="Projektordner (Standard: .)")
    parser.add_argument("--html", nargs="+", default=["index.html"], help="HTML-Dateien relativ zu --root")
    parser.add_argument("--loader", default="js/loader.js", help="Datei mit der Modultabelle des Laders")
    parser.add_argument("--check", action="store_true", help="nichts schreiben; Exit-Code 1, wenn Versionen veraltet sind")
    parser.add_argument("--manifest", help="schreibt eine Liste aller referenzierten Dateien (JSON)")
    parser.add_argument("--allow-missing", action="store_true", help="fehlende referenzierte Dateien nur melden (z. B. bei unvollständigem Checkout)")
    parser.add_argument("--copy-to", help="kopiert HTML-Dateien und alle referenzierten JS/CSS-Dateien (inkl. dynamisch geladener) in diesen Ordner")
    parser.add_argument("--verify-dir", help="prüft, ob alle Dateien des Manifests im Ordner vorhanden und aktuell sind")
    args = parser.parse_args()

    tool = Versioner(args.root, args.loader)
    try:
        for html in args.html:
            tool.process_html(html)
        # Der Lader ist u. U. nur über die Tabelle verbunden: sicherstellen, dass er verarbeitet wurde
        if (Path(args.root) / args.loader).is_file():
            tool.process(args.loader)
    except AssetError as error:
        print("FEHLER:", error, file=sys.stderr)
        return 2

    if tool.missing:
        label = "Hinweis" if args.allow_missing else "FEHLER"
        print(f"{label}: Verweise auf fehlende Dateien (bleiben unverändert):" if args.allow_missing else "FEHLER: Verweise auf fehlende Dateien:", file=sys.stderr)
        for parent, child in sorted(set(tool.missing)):
            print(f"  {parent} -> {child}", file=sys.stderr)
        if not args.allow_missing:
            return 2
    for warning in tool.warnings:
        print("Hinweis:", warning, file=sys.stderr)

    changed = [rel for rel, (text, _h) in tool.done.items() if text != tool.original[rel]]
    assets = {rel: h for rel, (text, h) in tool.done.items() if h is not None}

    if args.manifest:
        manifest = {
            "html": sorted(args.html),
            "assets": {rel: {"hash": assets[rel], "referencedBy": sorted(tool.referenced_by.get(rel, []))}
                       for rel in sorted(assets)},
        }
        Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Manifest: {args.manifest} ({len(assets)} Dateien)")

    status = 0
    if args.check:
        if changed:
            print("Veraltete Versionen in:", ", ".join(sorted(changed)), file=sys.stderr)
            status = 1
        else:
            print("Alle Versionen aktuell.")
    else:
        for rel in sorted(changed):
            with (Path(args.root) / rel).open("w", encoding="utf-8", newline="") as handle:
                handle.write(tool.done[rel][0])
        if changed:
            print(f"{len(changed)} Datei(en) aktualisiert:")
            for rel in sorted(changed):
                print("  " + rel)
        else:
            print("Keine Änderungen – alle Versionen sind aktuell.")
        print(f"{len(assets)} Dateien versioniert.")

    if args.copy_to and not args.check:
        target_root = Path(args.copy_to)
        for rel in sorted(list(assets) + list(args.html)):
            target = target_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(args.root) / rel, target)
        print(f"{len(assets) + len(args.html)} Dateien nach {target_root} kopiert.")

    if args.verify_dir:
        base = Path(args.verify_dir)
        problems = []
        for rel in sorted(list(assets) + list(args.html)):
            target = base / rel
            if not target.is_file():
                problems.append(f"fehlt im Build: {rel}")
                continue
            if rel in assets and digest(target.read_bytes()) != assets[rel]:
                problems.append(f"veraltet/abweichend im Build: {rel}")
            elif rel in args.html and target.read_bytes() != tool.done[rel][0].encode("utf-8"):
                problems.append(f"HTML veraltet/abweichend im Build: {rel}")
        if problems:
            print("VERIFIKATION FEHLGESCHLAGEN:", file=sys.stderr)
            for line in problems:
                print("  " + line, file=sys.stderr)
            status = 1
        else:
            print(f"Verifikation ok: {len(assets) + len(args.html)} Dateien in {base} vorhanden und aktuell")
    return status


if __name__ == "__main__":
    sys.exit(main())