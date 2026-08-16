from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "scripts" / "update_station_precip.py"
INDEX_PATH = ROOT / "index.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Patchstelle nicht gefunden: {label}")
    return text.replace(old, new, 1)


def patch_generator() -> None:
    text = GENERATOR_PATH.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "STATE_VERSION = 2",
        "STATE_VERSION = 3",
        "STATE_VERSION",
    )

    marker = "    return curves\n\n\ndef build_profile_payload("
    helper = '''    return curves


HISTORICAL_PERIOD_RANGES = {
    "spring": ("03-01", "05-31"),
    "summer": ("06-01", "08-31"),
    "autumn": ("09-01", "11-30"),
}


def build_historical_period_envelopes(curves: dict[int, list[float]]) -> dict[str, dict[str, Any]]:
    """Historische Hüllkurven, die am Beginn des gewählten Zeitraums bei 0 starten."""
    labels = labels_non_leap()
    label_index = {label: index for index, label in enumerate(labels)}
    result: dict[str, dict[str, Any]] = {}

    for period, (start_label, end_label) in HISTORICAL_PERIOD_RANGES.items():
        start_index = label_index[start_label]
        end_index = label_index[end_label]
        period_curves: dict[int, list[float]] = {}

        for year, curve in curves.items():
            if len(curve) <= end_index:
                continue
            base = curve[start_index - 1] if start_index > 0 else 0.0
            period_curves[year] = [
                round(curve[index] - base, 1)
                for index in range(start_index, end_index + 1)
            ]

        if not period_curves:
            continue

        historical_min: list[float] = []
        historical_max: list[float] = []
        historical_min_year: list[int] = []
        historical_max_year: list[int] = []

        for offset in range(end_index - start_index + 1):
            candidates = [(curve[offset], year) for year, curve in period_curves.items()]
            minimum = min(candidates, key=lambda item: (item[0], item[1]))
            maximum = max(candidates, key=lambda item: (item[0], -item[1]))
            historical_min.append(round(minimum[0], 1))
            historical_max.append(round(maximum[0], 1))
            historical_min_year.append(minimum[1])
            historical_max_year.append(maximum[1])

        result[period] = {
            "start_index": start_index,
            "end_index": end_index,
            "historical_min_cumulative": historical_min,
            "historical_max_cumulative": historical_max,
            "historical_min_year": historical_min_year,
            "historical_max_year": historical_max_year,
        }

    return result


def build_profile_payload('''
    text = replace_once(text, marker, helper, "Perioden-Hüllkurven")

    text = replace_once(
        text,
        "        historical_max_year.append(maximum[1])\n\n    segment = current_segment(metadata, station_id)",
        "        historical_max_year.append(maximum[1])\n\n    historical_periods = build_historical_period_envelopes(curves)\n\n    segment = current_segment(metadata, station_id)",
        "historical_periods berechnen",
    )

    text = replace_once(
        text,
        '        "historical_max_year": historical_max_year,\n',
        '        "historical_max_year": historical_max_year,\n        "historical_periods": historical_periods,\n',
        "historical_periods Payload",
    )

    GENERATOR_PATH.write_text(text, encoding="utf-8")


def patch_frontend() -> None:
    text = INDEX_PATH.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '<div class="stat-card"><h4>Historischer Spannbereich (ab 01.01.)</h4><div id="stationPrecipRangeStat">–</div></div>',
        '<div class="stat-card"><h4>Historischer Spannbereich</h4><div id="stationPrecipRangeStat">–</div></div>',
        "Spannbereich Überschrift",
    )

    old = '''    let historicalMin=[],historicalMax=[],minValue=null,maxValue=null,minYear=null,maxYear=null;
    const ytdCompatible=range.startIndex===0;
    if(ytdCompatible){
      historicalMin=(stationPrecipProfile.historical_min_cumulative||[]).slice(range.startIndex,range.endIndex+1);
      historicalMax=(stationPrecipProfile.historical_max_cumulative||[]).slice(range.startIndex,range.endIndex+1);
      minValue=historicalMin.length?historicalMin[historicalMin.length-1]:null;
      maxValue=historicalMax.length?historicalMax[historicalMax.length-1]:null;
      minYear=(stationPrecipProfile.historical_min_year||[])[range.endIndex]??null;
      maxYear=(stationPrecipProfile.historical_max_year||[])[range.endIndex]??null;
    }'''
    new = '''    let historicalMin=[],historicalMax=[],minValue=null,maxValue=null,minYear=null,maxYear=null;
    const ytdCompatible=range.startIndex===0;
    const periodHistory=stationPrecipProfile.historical_periods?.[range.period]??null;
    const periodCompatible=Boolean(periodHistory)
      && Number(periodHistory.start_index)===range.startIndex
      && range.endIndex<=Number(periodHistory.end_index);
    const historicalCompatible=ytdCompatible||periodCompatible;
    if(ytdCompatible){
      historicalMin=(stationPrecipProfile.historical_min_cumulative||[]).slice(range.startIndex,range.endIndex+1);
      historicalMax=(stationPrecipProfile.historical_max_cumulative||[]).slice(range.startIndex,range.endIndex+1);
      minValue=historicalMin.length?historicalMin[historicalMin.length-1]:null;
      maxValue=historicalMax.length?historicalMax[historicalMax.length-1]:null;
      minYear=(stationPrecipProfile.historical_min_year||[])[range.endIndex]??null;
      maxYear=(stationPrecipProfile.historical_max_year||[])[range.endIndex]??null;
    }else if(periodCompatible){
      const endOffset=range.endIndex-range.startIndex;
      historicalMin=(periodHistory.historical_min_cumulative||[]).slice(0,endOffset+1);
      historicalMax=(periodHistory.historical_max_cumulative||[]).slice(0,endOffset+1);
      minValue=historicalMin.length?historicalMin[historicalMin.length-1]:null;
      maxValue=historicalMax.length?historicalMax[historicalMax.length-1]:null;
      minYear=(periodHistory.historical_min_year||[])[endOffset]??null;
      maxYear=(periodHistory.historical_max_year||[])[endOffset]??null;
    }'''
    text = replace_once(text, old, new, "historische Frontend-Kurven")

    text = replace_once(
        text,
        '''    document.getElementById("stationPrecipRangeStat").textContent=ytdCompatible&&minValue!==null
      ?`${stationPrecipFormat(minValue)} mm (${minYear}) bis ${stationPrecipFormat(maxValue)} mm (${maxYear})`
      :"Für Zeiträume mit Start nach dem 01.01. nicht vorab berechnet";''',
        '''    document.getElementById("stationPrecipRangeStat").textContent=historicalCompatible&&minValue!==null
      ?`${stationPrecipFormat(minValue)} mm (${minYear}) bis ${stationPrecipFormat(maxValue)} mm (${maxYear})`
      :"Für diesen Zeitraum nicht vorab berechnet";''',
        "Spannbereich Statistik",
    )

    text = replace_once(
        text,
        '    if(!ytdCompatible) gapText+=" Der historische Min-Max-Spannbereich wird bei frei beginnenden Zeiträumen bewusst nicht angezeigt, weil die bisher gespeicherten historischen Hüllkurven auf den 1. Januar bezogen sind.";',
        '    if(!historicalCompatible) gapText+=" Der historische Min-Max-Spannbereich ist derzeit für Seit Jahresbeginn sowie Frühling, Sommer und Herbst verfügbar.";',
        "Spannbereich Hinweis",
    )

    text = replace_once(
        text,
        "    if(ytdCompatible){\n      datasets.push(",
        "    if(historicalCompatible){\n      datasets.push(",
        "Hüllkurven-Datasets",
    )

    INDEX_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    patch_generator()
    patch_frontend()
    print("Saison-Hüllkurven-Patch erfolgreich angewendet.")


if __name__ == "__main__":
    main()
