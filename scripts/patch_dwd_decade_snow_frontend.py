#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: genau 1 Treffer erwartet, gefunden: {count}"
        )
    return text.replace(old, new, 1)


def patch(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    old_options = '''        <option value="txk_high">Tmax · höchstes Maximum</option>
        <option value="txk_low">Tmax · niedrigstes Maximum</option>
        <option value="tnk_high">Tmin · höchstes Minimum</option>
        <option value="tnk_low">Tmin · tiefstes Minimum</option>'''
    new_options = old_options + '''
        <option value="shk_high">Schneehöhe · höchster Wert</option>'''
    if '<option value="shk_high">' not in text:
        text = replace_once(text, old_options, new_options, "Schnee-Option")

    old_method = '''    Stationen. Für jede meteorologische Dekade werden pro Station höchstes und
    niedrigstes Tmax sowie höchstes und niedrigstes Tmin bestimmt. Rangliste und Karte
    verwenden je Station deren persönlichen Dekadenrekord. Ein gesetzter Höhenfilter berücksichtigt nur Stationen,
    deren DWD-Stationshöhe höchstens dem eingegebenen Wert entspricht.
    Die Bundeslandzuordnung folgt den DWD-Stationsmetadaten zum jeweiligen Messtag.'''
    new_method = '''    Stationen. Für jede meteorologische Dekade werden pro Station höchstes und
    niedrigstes Tmax, höchstes und niedrigstes Tmin sowie die höchste gemessene
    Schneehöhe (SHK_TAG/SHK) bestimmt. Rangliste und Karte verwenden je Station deren
    persönlichen Dekadenrekord. Ein gesetzter Höhenfilter berücksichtigt nur Stationen,
    deren DWD-Stationshöhe höchstens dem eingegebenen Wert entspricht.
    Die Bundeslandzuordnung folgt den DWD-Stationsmetadaten zum jeweiligen Messtag.'''
    if "Schneehöhe (SHK_TAG/SHK)" not in text:
        text = replace_once(text, old_method, new_method, "Methodik")

    old_urls = '  const DATA_URL = "data/dwd_decade_records.json";'
    new_urls = '''  const DATA_URL = "data/dwd_decade_records.json";
  const SNOW_DATA_URL = "data/dwd_decade_snow_records.json";'''
    if "SNOW_DATA_URL" not in text:
        text = replace_once(text, old_urls, new_urls, "Schnee-Daten-URL")

    old_state = '''  let data = null;
  let map = null;'''
    new_state = '''  let data = null;
  let snowData = null;
  let map = null;'''
    if "let snowData = null;" not in text:
        text = replace_once(text, old_state, new_state, "Schnee-Datenzustand")

    old_station = '''  function stationFromEntry(entry) {
    if (!entry || entry.length < 3) return null;
    return data.stations?.[entry[2]] ?? null;
  }'''
    new_station = '''  function activeData(metric = els.metric.value) {
    return metric === "shk_high" ? snowData : data;
  }

  function stationFromEntry(entry) {
    if (!entry || entry.length < 3) return null;
    return activeData()?.stations?.[entry[2]] ?? null;
  }'''
    if "function activeData(" not in text:
        text = replace_once(text, old_station, new_station, "Aktiver Datensatz")

    old_meta = '''  function metricMeta(metric) {
    return data.metrics?.[metric] ?? {
      label: metric,
      unit: "°C",
      direction: metric === "tnk_low" ? "asc" : "desc"
    };
  }'''
    new_meta = '''  function metricMeta(metric) {
    if (metric === "shk_high") {
      return snowData?.metric_meta ?? {
        label: "Höchste Schneehöhe",
        unit: "cm",
        direction: "desc"
      };
    }
    return data.metrics?.[metric] ?? {
      label: metric,
      unit: "°C",
      direction: metric.endsWith("_low") ? "asc" : "desc"
    };
  }'''
    meta_slice = text[text.find("function metricMeta"):text.find("function periodId")]
    if 'metric === "shk_high"' not in meta_slice:
        text = replace_once(text, old_meta, new_meta, "Parameter-Metadaten")

    old_marker = '''  function markerRecords() {
    const metric = els.metric.value;
    const area = els.area.value;
    const period = periodId();
    const raw = data.station_records?.[metric]?.[area]?.[period] ?? {};
    const limit = maxHeightLimit();'''
    new_marker = '''  function markerRecords() {
    const metric = els.metric.value;
    const area = els.area.value;
    const period = periodId();
    const source = activeData(metric);
    const raw = metric === "shk_high"
      ? (source?.station_records?.[area]?.[period] ?? {})
      : (source?.station_records?.[metric]?.[area]?.[period] ?? {});
    const limit = maxHeightLimit();'''
    if "source?.station_records?.[area]?.[period]" not in text:
        text = replace_once(text, old_marker, new_marker, "Schnee-Stationsrekorde")

    old_color = '''    let t = (value - min) / (max - min);
    t = Math.max(0, Math.min(1, t));

    const cold = [47, 111, 212];'''
    new_color = '''    let t = (value - min) / (max - min);
    t = Math.max(0, Math.min(1, t));

    if (els.metric.value === "shk_high") {
      const pale = [229, 232, 235];
      const blue = [47, 111, 212];
      const rgb = pale.map((v, i) => Math.round(v + (blue[i] - v) * t));
      return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
    }

    const cold = [47, 111, 212];'''
    color_slice = text[text.find("function colorFor"):text.find("function markerRecords")]
    if 'els.metric.value === "shk_high"' not in color_slice:
        text = replace_once(text, old_color, new_color, "Schnee-Kartenfarbe")

    old_summary = '    els.recordValue.className = `summary-value ${metric.endsWith("_high") ? "hot" : "cold"}`;'
    new_summary = '''    els.recordValue.className = `summary-value ${
      metric === "shk_high" ? "cold" : (metric.endsWith("_high") ? "hot" : "cold")
    }`;'''
    if 'metric === "shk_high" ? "cold"' not in text:
        text = replace_once(text, old_summary, new_summary, "Schnee-Zusammenfassungsfarbe")

    old_dates = '''    els.stationCount.textContent = Object.keys(records).length.toLocaleString("de-DE");
    els.dataThrough.textContent = formatShortDate(data.data_through);
    els.dataRange.textContent =
      `${formatDate(data.data_start)} bis ${formatDate(data.data_through)}`;'''
    new_dates = '''    els.stationCount.textContent = Object.keys(records).length.toLocaleString("de-DE");
    const source = activeData(metric);
    els.dataThrough.textContent = formatShortDate(source?.data_through);
    els.dataRange.textContent =
      `${formatDate(source?.data_start)} bis ${formatDate(source?.data_through)}`;'''
    if "formatShortDate(source?.data_through)" not in text:
        text = replace_once(text, old_dates, new_dates, "Parameter-Datenstand")

    old_render_guard = '''  function render() {
    if (!data) return;'''
    new_render_guard = '''  function render() {
    if (!data || !snowData) return;'''
    if "if (!data || !snowData) return;" not in text:
        text = replace_once(text, old_render_guard, new_render_guard, "Render-Prüfung")

    old_load = '''  async function loadData() {
    try {
      const response = await fetch(DATA_URL, {cache:"no-cache"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      data = await response.json();

      if (!Array.isArray(data.areas) || data.areas.length !== 17) {
        throw new Error("Gebietsliste unvollständig");
      }
      if (!Array.isArray(data.periods) || data.periods.length !== 36) {
        throw new Error("Dekadenliste unvollständig");
      }

      setupControls();
      setupMap();

      els.status.textContent =
        `DWD · Datenstand ${formatDate(data.data_through)} · ` +
        `${data.areas.length} Gebiete · ${data.periods.length} Dekaden`;
      render();
    } catch (error) {
      console.error(error);
      els.status.classList.add("error");
      els.status.textContent =
        `Dekadenrekorde konnten nicht geladen werden: ${error.message}`;
      els.rankingBody.innerHTML =
        '<tr><td colspan="6" class="empty">Daten konnten nicht geladen werden.</td></tr>';
    }
  }'''
    new_load = '''  async function loadData() {
    try {
      const [tempResponse, snowResponse] = await Promise.all([
        fetch(DATA_URL, {cache:"no-cache"}),
        fetch(SNOW_DATA_URL, {cache:"no-cache"})
      ]);

      if (!tempResponse.ok) {
        throw new Error(`Temperaturdaten: HTTP ${tempResponse.status}`);
      }
      if (!snowResponse.ok) {
        throw new Error(`Schneedaten: HTTP ${snowResponse.status}`);
      }

      [data, snowData] = await Promise.all([
        tempResponse.json(),
        snowResponse.json()
      ]);

      if (!Array.isArray(data.areas) || data.areas.length !== 17) {
        throw new Error("Temperatur-Gebietsliste unvollständig");
      }
      if (!Array.isArray(data.periods) || data.periods.length !== 36) {
        throw new Error("Temperatur-Dekadenliste unvollständig");
      }
      if (!Array.isArray(snowData.areas) || snowData.areas.length !== 17) {
        throw new Error("Schnee-Gebietsliste unvollständig");
      }
      if (!Array.isArray(snowData.periods) || snowData.periods.length !== 36) {
        throw new Error("Schnee-Dekadenliste unvollständig");
      }
      if (snowData.metric !== "shk_high") {
        throw new Error("Schnee-Parameter fehlt");
      }

      setupControls();
      setupMap();

      els.status.textContent =
        `DWD · Temperatur bis ${formatDate(data.data_through)} · ` +
        `Schnee bis ${formatDate(snowData.data_through)} · ` +
        `${data.areas.length} Gebiete · ${data.periods.length} Dekaden`;
      render();
    } catch (error) {
      console.error(error);
      els.status.classList.add("error");
      els.status.textContent =
        `Dekadenrekorde konnten nicht geladen werden: ${error.message}`;
      els.rankingBody.innerHTML =
        '<tr><td colspan="6" class="empty">Daten konnten nicht geladen werden.</td></tr>';
    }
  }'''
    if "const [tempResponse, snowResponse]" not in text:
        text = replace_once(text, old_load, new_load, "Laden der Schnee-Datenbasis")

    required = [
        '<option value="shk_high">Schneehöhe · höchster Wert</option>',
        'const SNOW_DATA_URL = "data/dwd_decade_snow_records.json";',
        "let snowData = null;",
        "function activeData(",
        "source?.station_records?.[area]?.[period]",
        'els.metric.value === "shk_high"',
        "const [tempResponse, snowResponse]",
        'snowData.metric !== "shk_high"',
        "Schneehöhe (SHK_TAG/SHK)",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError(
            "Schnee-Frontend-Prüfung fehlgeschlagen: " + ", ".join(missing)
        )

    changed = text != original
    if changed:
        path.write_text(text, encoding="utf-8")
        print("Schneehöhe in Dekadenrekord-Frontend eingebaut.")
    else:
        print("Schneehöhe ist bereits vollständig eingebaut.")

    return changed


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
