#!/usr/bin/env python3
"""Inject the shared MOBILE navigation in all root HTML pages of the Pages artifact.

The desktop markup and all individual module controls are not changed.
Run only against a generated output folder, not the source HTML pages.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re

VERSION="20261030-mobile-categories-v2"
STYLE=f'<link rel="stylesheet" href="mobile_navigation.css?v={VERSION}">'
CONTENT_STYLE=f'<link rel="stylesheet" href="mobile_content.css?v={VERSION}">'
SCRIPT=f'<script defer src="mobile_navigation.js?v={VERSION}"></script>'
SATELLITE_SHORTCUT=(
    '<nav class="cdm-satellite-quicknav" aria-label="Direktzugang zu Satellitenbildern">'
    '<a id="cdSatelliteShortcut" class="cdm-satellite-shortcut" href="./satelliten.html">'
    '🛰 Satellitenbilder öffnen</a></nav>'
)


def inject_satellite_shortcut(content: str) -> str:
    """Insert a visible, functional homepage link even with JavaScript disabled.

    Only the generated Pages copy is modified; the enormous source index.html
    remains untouched and the injection is idempotent.
    """
    if 'id="cdSatelliteShortcut"' in content:
        return content
    header = re.search(r"</header\s*>", content, re.I)
    if header:
        return content[:header.end()] + "\n" + SATELLITE_SHORTCUT + content[header.end():]
    body = re.search(r"<body\b[^>]*>", content, re.I)
    if not body:
        raise ValueError("Could not add satellite homepage shortcut: missing body")
    return content[:body.end()] + "\n" + SATELLITE_SHORTCUT + content[body.end():]

CONTENT_SCRIPT=f'<script defer src="mobile_content.js?v={VERSION}"></script>'


def inject(content: str) -> str:
    """Idempotent injection of navigation and mobile-only visual improvements."""
    assets = (
        ("mobile_navigation.css", STYLE, r"</head\s*>"),
        ("mobile_content.css", CONTENT_STYLE, r"</head\s*>"),
        ("mobile_navigation.js", SCRIPT, r"</body\s*>"),
        ("mobile_content.js", CONTENT_SCRIPT, r"</body\s*>"),
    )
    for name, tag, closing in assets:
        if name not in content:
            if not re.search(closing, content, re.I):
                raise ValueError(f"HTML closing tag missing for {name}")
            content=re.sub(closing,lambda match:tag+"\n"+match.group(0),
                           content,count=1,flags=re.I)
        if content.count(name)!=1:
            raise ValueError(f"Missing or duplicate mobile asset: {name}")
    return content

def deploy(output: Path) -> list[str]:
    if not output.is_dir():
        raise FileNotFoundError(output)
    if not (output/"mobile_navigation.js").is_file():
        raise FileNotFoundError(output/"mobile_navigation.js")
    if not (output/"mobile_navigation.css").is_file():
        raise FileNotFoundError(output/"mobile_navigation.css")
    for asset in ("mobile_content.js", "mobile_content.css"):
        if not (output/asset).is_file():
            raise FileNotFoundError(output/asset)
    pages=sorted(output.glob("*.html"))
    if not pages or not (output/"index.html").exists():
        raise RuntimeError("Pages output missing index.html")
    updated=[]
    # Validate every page first to avoid partial publishing.
    staged=[]
    for path in pages:
        content=path.read_text(encoding="utf-8")
        published=inject(content)
        if path.name=="index.html":
            published=inject_satellite_shortcut(published)
        staged.append((path,published))
    for path,content in staged:
        if path.read_text(encoding="utf-8")!=content:
            path.write_text(content,encoding="utf-8")
        updated.append(path.name)
    return updated


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("output",type=Path,help="Generated Pages directory, for example _site")
    args=parser.parse_args()
    paths=deploy(args.output)
    print(f"Unified mobile categories deployed to {len(paths)} HTML pages: "+", ".join(paths))


if __name__=="__main__":
    main()
