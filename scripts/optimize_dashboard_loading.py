"""Transform the built dashboard only; leave source and standalone pages intact."""

import argparse
import hashlib
import re
from pathlib import Path

HYRAS_START = b"// ================= VERSION 9: ZUSTAND, MOBILE NAVIGATION, CSV ================="
MAIN = re.compile(rb"<script>(\s*(?:Chart\.register\(ChartDataLabels\);|// Start-Abrufe|" + re.escape(HYRAS_START) + rb").*?)</script>", re.S)
EXTERNAL = re.compile(rb"<script\b(?=[^>]*\bsrc=)[^>]*>\s*</script>")


def versioned_script(name, content, defer=False):
    version = hashlib.sha256(content).hexdigest()[:16]
    return f'<script {"defer " if defer else ""}src="{name}?v={version}"></script>'.encode()


def extract(html, site):
    matches = list(MAIN.finditer(html))
    if not matches:
        modules = ("era5-land", "europa-stationen", "dashboard-state", "hyras-tmin", "bootstrap")
        positions = []
        for module in modules:
            filename = f"js/{module}.js"
            tags = [tag for tag in EXTERNAL.finditer(html)
                    if re.search(rb'src="' + re.escape(filename.encode()) + rb'(?:\?|")', tag[0])]
            if len(tags) != 1 or not (site / filename).is_file():
                raise ValueError(f"Missing or duplicate split dashboard module: {filename}")
            positions.append(tags[0].start())
        if positions != sorted(positions):
            raise ValueError("Bootstrap must follow the dashboard definitions and HYRAS overrides")
        return html
    if len(matches) == 1 and not matches[0][1].lstrip().startswith(HYRAS_START):
        names = ("dashboard_main.js",)
    elif len(matches) == 2 and matches[0][1].lstrip().startswith(HYRAS_START) and matches[1][1].lstrip().startswith(b"// Start-Abrufe"):
        names = ("dashboard_hyras.js", "dashboard_main.js")
    else:
        raise ValueError("Unexpected dashboard inline-script layout")
    for match, name in reversed(list(zip(matches, names))):
        content = match[1]
        (site / name).write_bytes(content)
        html = html[:match.start()] + versioned_script(name, content) + html[match.end():]
    return html


def defer_scripts(html):
    # Existing deferred scripts originally executed after all synchronous
    # scripts. Preserve that ordering when the synchronous scripts become defer.
    tail = []

    def transform(match):
        tag = match[0]
        if re.search(rb"\sdefer(?:\s|>)", tag):
            tail.append(tag)
            return b""
        tag = re.sub(rb"\sasync(?=\s|>)", b"", tag)
        return tag.replace(b"<script", b"<script defer", 1)

    html = EXTERNAL.sub(transform, html)
    if html.count(b"</body>") != 1:
        raise ValueError("Expected exactly one closing body")
    return html.replace(b"</body>", b"\n".join(tail) + b"\n</body>")


PDF = "await window.dashboardExportLibraries.pdf();"
CANVAS = "await window.dashboardExportLibraries.canvas();"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Export integration anchor changed: {old!r}")
    return source.replace(old, new)


def lazy_exports(html, site):
    # Modify only the generated copies used by index.html. Standalone pages
    # can continue using their own eager libraries and original files.
    loader = (Path(__file__).with_name("dashboard_export_libraries.js")).read_bytes()
    (site / "dashboard_export_libraries.js").write_bytes(loader)
    for name in (b"npm/jspdf@", b"npm/html2canvas@"):
        html, count = EXTERNAL.subn(lambda match: b"" if name in match[0] else match[0], html)
    main_tag = next(tag[0] for tag in EXTERNAL.finditer(html) if b"js/export-karten-vergleich.js?" in tag[0] or b"dashboard_main.js?" in tag[0])
    html = html.replace(main_tag, versioned_script("dashboard_export_libraries.js", loader, True) + b"\n" + main_tag)

    edits = {
        "dashboard_main.js": [
            ('  if(typeof html2canvas!=="function"){alert("Die Exportbibliothek konnte nicht geladen werden.");return;}\n', ''),
            ('  if(typeof html2canvas!=="function"){\n    alert("Die Exportbibliothek konnte nicht geladen werden.");\n    return;\n  }\n', ''),
            ('    const area=document.getElementById("stationProfileClimateValuesExportArea");', '    ' + CANVAS + '\n    const area=document.getElementById("stationProfileClimateValuesExportArea");'),
            ('    const {jsPDF}=window.jspdf||{};if(!jsPDF)', '    ' + PDF + '\n    const {jsPDF}=window.jspdf||{};if(!jsPDF)'),
            ('function exportChartAsPdf(canvas){', 'async function exportChartAsPdf(canvas){\n  ' + PDF),
            ('else exportChartAsPdf(canvas);', 'else await exportChartAsPdf(canvas);'),
            *[(f'    const canvas=document.getElementById("hyras{kind}RegionCanvas");\n    const JsPdf=', f'    {PDF}\n    const canvas=document.getElementById("hyras{kind}RegionCanvas");\n    const JsPdf=') for kind in ('Tmean', 'Tmax', 'Tmin')],
            ("  if(typeof html2canvas!=='function') throw new Error('Exportbibliothek konnte nicht geladen werden.');", '  ' + CANVAS),
            ('    const {jsPDF}=window.jspdf||{};\n', '    ' + PDF + '\n    const {jsPDF}=window.jspdf||{};\n'),
            ('    const jsPDFCtor=window.jspdf?.jsPDF;', '    ' + PDF + '\n    const jsPDFCtor=window.jspdf?.jsPDF;'),
        ],
        "dashboard_theme.js": [('    if(typeof window.html2canvas!==', '    ' + CANVAS + '\n    if(typeof window.html2canvas!==')],
        "monthly_frequency.js": [
            ('    if(typeof html2canvas!==', '    ' + CANVAS + '\n    if(typeof html2canvas!=='),
            ('    const canvas=await monthlyFrequencyExportCanvas(),jsPDFCtor=', '    ' + PDF + '\n    const canvas=await monthlyFrequencyExportCanvas(),jsPDFCtor='),
        ],
        "state_monthly_ensemble.js": [
            ('try{if(!window.html2canvas)throw', 'try{' + CANVAS + 'if(!window.html2canvas)throw'),
            ('try{if(!window.html2canvas||!window.jspdf', 'try{' + CANVAS + PDF + 'if(!window.html2canvas||!window.jspdf'),
        ],
        "t850_ensembles.js": [
            ('  if(!window.html2canvas)', '  ' + CANVAS + '\n  if(!window.html2canvas)'),
            ('    const exporter=await ensureT850Vectors(),J=', '    ' + PDF + '\n    const exporter=await ensureT850Vectors(),J='),
        ],
        "sst_europe.js": [('    const JsPdf=window.jspdf', '    ' + PDF + '\n    const JsPdf=window.jspdf')],
        "station_thresholds.js": [
            ('  function exportPdf(){', '  async function exportPdf(){'),
            ('    if(!window.jspdf||!window.jspdf.jsPDF)', '    try{' + PDF + '}catch(error){setStatus(error.message);return;}\n    if(!window.jspdf||!window.jspdf.jsPDF)'),
        ],
        "gebietsmittel_archiv.js": [
            ("try{const node=$('gaExportArea');", "try{" + CANVAS + "if(kind==='pdf'){" + PDF + "}const node=$('gaExportArea');"),
        ],
        "mosmix.js": [('  function ensurePdfLibrary(){', '  function ensurePdfLibrary(){\n    if(window.dashboardExportLibraries)return window.dashboardExportLibraries.pdf();')],
        "scientific_vector_actions.js": [('function jsPDF(){', 'function jsPDF(){\n if(root.dashboardExportLibraries)return root.dashboardExportLibraries.pdf();')],
    }
    # The first thematic split moves the regional-map PNG entry point out
    # of the remaining main script. Keep the same lazy-export guarantee.
    regional_guard = edits["dashboard_main.js"][0]
    if (site / "js/gebietsmittel.js").is_file():
        edits["dashboard_main.js"].remove(regional_guard)
        edits["js/gebietsmittel.js"] = [regional_guard, (
            '  try{\n    const mapObj=mapName===',
            '  try{\n    ' + CANVAS + '\n    const mapObj=mapName===',
        )]
    if (site / "js/stationen-kenntage.js").is_file():
        main_edits = edits["dashboard_main.js"]
        for filename, anchors in {
            "js/stationen-kenntage.js": ('stationProfileClimateValuesExportArea', 'const {jsPDF}=window.jspdf||{};if(!jsPDF)'),
            "js/stationen-auswertungen.js": ('  if(typeof html2canvas!=="function"){\n',),
        }.items():
            moved = [edit for edit in main_edits if any(anchor in edit[0] for anchor in anchors)]
            assert len(moved) == len(anchors)
            edits[filename] = moved
            for edit in moved:
                main_edits.remove(edit)
        edits["js/stationen-auswertungen.js"].append((
            '  try{\n    controls.forEach(node=>{node.style.display="none";});',
            '  try{\n    ' + CANVAS + '\n    controls.forEach(node=>{node.style.display="none";});',
        ))
    # The third split distributes the remaining export entry points across
    # multiple classic scripts. Each anchor must still have exactly one owner.
    candidates = [name for name in ("dashboard_main.js", "dashboard_hyras.js", "js/export-karten-vergleich.js", "js/stationsprofil.js", "js/aktuell.js", "js/hyras.js", "js/hyras-tmin.js", "js/era5-land.js", "js/europa-stationen.js", "js/dashboard-state.js", "js/bootstrap.js") if (site / name).is_file()]
    sources = {name: (site / name).read_text() for name in candidates}
    pending = edits.pop("dashboard_main.js")
    for old, new in pending:
        owners = [name for name in candidates if old in sources[name]]
        if len(owners) != 1:
            raise ValueError(f"Export integration anchor has unexpected owners: {old!r}: {owners}")
        edits.setdefault(owners[0], []).append((old, new))
    for filename, replacements in edits.items():
        path = site / filename
        original = path.read_bytes().decode()
        modified = original
        for old, new in replacements:
            modified = replace_once(modified, old, new)
        content = modified.encode()
        # Keep standalone pages using the unchanged original module.
        target = filename if filename in ("dashboard_main.js", "dashboard_hyras.js") else filename.removesuffix(".js") + ".optimized.js"
        (site / target).write_bytes(content)
        # Some modules are injected only by the Pages build.
        tags = [tag[0] for tag in EXTERNAL.finditer(html) if re.search(rb'src="' + re.escape(filename.encode()) + rb'(?:\?|")', tag[0])]
        for tag in tags:
            html = html.replace(tag, versioned_script(target, content, True))
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    parser.add_argument("--stage", choices=("extract", "defer", "lazy"), default="lazy")
    args = parser.parse_args()
    index = args.site / "index.html"
    html = extract(index.read_bytes(), args.site)
    if args.stage in ("defer", "lazy"):
        html = defer_scripts(html)
    if args.stage == "lazy":
        html = lazy_exports(html, args.site)
    index.write_bytes(html)


if __name__ == "__main__":
    main()
