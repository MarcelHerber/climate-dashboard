#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path

def rep(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: 1 Treffer erwartet, gefunden {n}")
    return text.replace(old, new, 1)

def patch(path: Path):
    text = path.read_text(encoding="utf-8")
    original = text

    if '<option value="p_high">' not in text:
        text = rep(text,
'''        <option value="tnk_low">Tmin · tiefstes Minimum</option>
        <option value="shk_high">Schneehöhe · höchster Wert</option>''',
'''        <option value="tnk_low">Tmin · tiefstes Minimum</option>
        <option value="shk_high">Schneehöhe · höchster Wert</option>
        <option value="p_high">Luftdruck NN · höchster Wert</option>
        <option value="p_low">Luftdruck NN · niedrigster Wert</option>''',
"Parameter")

    if "QN-1-Rekordkandidaten" not in text:
        text = rep(text,
'''    <strong>Methodik:</strong> Grundlage sind tägliche DWD-CDC-Klimadaten der deutschen
    Stationen. Für jede meteorologische Dekade werden pro Station höchstes und
    niedrigstes Tmax, höchstes und niedrigstes Tmin sowie die höchste gemessene
    Schneehöhe (SHK_TAG/SHK) bestimmt. Rangliste und Karte verwenden je Station deren
    persönlichen Dekadenrekord. Ein gesetzter Höhenfilter berücksichtigt nur Stationen,
    deren DWD-Stationshöhe höchstens dem eingegebenen Wert entspricht.
    Die Bundeslandzuordnung folgt den DWD-Stationsmetadaten zum jeweiligen Messtag.''',
'''    <strong>Methodik:</strong> Temperatur und Schneehöhe stammen aus täglichen
    DWD-CDC-Klimadaten. Für Luftdruck wird der stündliche DWD-Datensatz verwendet;
    ausgewertet wird P = auf Meereshöhe NN reduzierter Luftdruck. Für jede meteorologische
    Dekade werden pro Station höchstes und niedrigstes Tmax, höchstes und niedrigstes Tmin,
    höchste Schneehöhe sowie höchster und niedrigster Luftdruck NN bestimmt. Beim Luftdruck
    werden Stationen über 750 m ausgeschlossen; QN-1-Rekordkandidaten werden zusätzlich
    durch zeitgleiche Messungen anderer DWD-Stationen plausibilisiert. Rangliste und Karte
    verwenden je Station deren persönlichen Dekadenrekord. Ein gesetzter Höhenfilter
    berücksichtigt nur Stationen, deren DWD-Stationshöhe höchstens dem eingegebenen Wert
    entspricht. Die Bundeslandzuordnung folgt den DWD-Stationsmetadaten zum jeweiligen
    Messtag.''',
"Methodik")

    if "PRESSURE_DATA_URL" not in text:
        text = rep(text,
'''  const DATA_URL = "data/dwd_decade_records.json";
  const SNOW_DATA_URL = "data/dwd_decade_snow_records.json";''',
'''  const DATA_URL = "data/dwd_decade_records.json";
  const SNOW_DATA_URL = "data/dwd_decade_snow_records.json";
  const PRESSURE_DATA_URL = "data/dwd_decade_pressure_records.json";''',
"URL")

    if "let pressureData = null;" not in text:
        text = rep(text,
'''  let data = null;
  let snowData = null;
  let map = null;''',
'''  let data = null;
  let snowData = null;
  let pressureData = null;
  let map = null;''',
"State")

    if 'metric === "p_high" || metric === "p_low"' not in text:
        text = rep(text,
'''  function activeData(metric = els.metric.value) {
    return metric === "shk_high" ? snowData : data;
  }''',
'''  function activeData(metric = els.metric.value) {
    if (metric === "shk_high") return snowData;
    if (metric === "p_high" || metric === "p_low") return pressureData;
    return data;
  }''',
"activeData")

    if "pressureData?.metrics?.[metric]" not in text:
        text = rep(text,
'''  function metricMeta(metric) {
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
  }''',
'''  function metricMeta(metric) {
    if (metric === "shk_high") {
      return snowData?.metric_meta ?? {
        label: "Höchste Schneehöhe",
        unit: "cm",
        direction: "desc"
      };
    }
    if (metric === "p_high" || metric === "p_low") {
      return pressureData?.metrics?.[metric] ?? {
        label: metric === "p_high" ? "Höchster Luftdruck NN" : "Niedrigster Luftdruck NN",
        unit: "hPa",
        direction: metric === "p_low" ? "asc" : "desc"
      };
    }
    return data.metrics?.[metric] ?? {
      label: metric,
      unit: "°C",
      direction: metric.endsWith("_low") ? "asc" : "desc"
    };
  }''',
"metricMeta")

    if "const timeText =" not in text:
        text = rep(text,
'''      els.recordDate.textContent = formatShortDate(first[1]);
      els.recordDateDetail.textContent =
        `${formatDate(first[1])}${first[3] ? " · vorläufig" : ""}`;''',
'''      els.recordDate.textContent = formatShortDate(first[1]);
      const timeText = (metric === "p_high" || metric === "p_low") && first[4]
        ? ` · ${first[4]}`
        : "";
      els.recordDateDetail.textContent =
        `${formatDate(first[1])}${timeText}${first[3] ? " · vorläufig" : ""}`;''',
"Summary-Zeit")

    if "escapeHtml(entry[4])" not in text:
        text = rep(text,
'''          <td>${escapeHtml(formatDate(entry[1]))}</td>
          <td>''',
'''          <td>
            ${escapeHtml(formatDate(entry[1]))}
            ${(els.metric.value === "p_high" || els.metric.value === "p_low") && entry[4]
              ? `<br><span style="color:#777;font-size:11px">${escapeHtml(entry[4])}</span>`
              : ""}
          </td>
          <td>''',
"Tabellen-Zeit")

    if "escapeHtml(point.entry[4])" not in text:
        text = rep(text,
'''          <div>${escapeHtml(formatDate(point.entry[1]))}</div>
          <div class="popup-meta">''',
'''          <div>
            ${escapeHtml(formatDate(point.entry[1]))}
            ${(els.metric.value === "p_high" || els.metric.value === "p_low") && point.entry[4]
              ? ` · ${escapeHtml(point.entry[4])}`
              : ""}
          </div>
          <div class="popup-meta">''',
"Popup-Zeit")

    if "if (!data || !snowData || !pressureData) return;" not in text:
        text = rep(text,
'''  function render() {
    if (!data || !snowData) return;''',
'''  function render() {
    if (!data || !snowData || !pressureData) return;''',
"Render")

    if "pressureResponse" not in text:
        text = rep(text,
'''      const [tempResponse, snowResponse] = await Promise.all([
        fetch(DATA_URL, {cache:"no-cache"}),
        fetch(SNOW_DATA_URL, {cache:"no-cache"})
      ]);''',
'''      const [tempResponse, snowResponse, pressureResponse] = await Promise.all([
        fetch(DATA_URL, {cache:"no-cache"}),
        fetch(SNOW_DATA_URL, {cache:"no-cache"}),
        fetch(PRESSURE_DATA_URL, {cache:"no-cache"})
      ]);''',
"Fetch")

        text = rep(text,
'''      if (!snowResponse.ok) {
        throw new Error(`Schneedaten: HTTP ${snowResponse.status}`);
      }

      [data, snowData] = await Promise.all([
        tempResponse.json(),
        snowResponse.json()
      ]);''',
'''      if (!snowResponse.ok) {
        throw new Error(`Schneedaten: HTTP ${snowResponse.status}`);
      }
      if (!pressureResponse.ok) {
        throw new Error(`Luftdruckdaten: HTTP ${pressureResponse.status}`);
      }

      [data, snowData, pressureData] = await Promise.all([
        tempResponse.json(),
        snowResponse.json(),
        pressureResponse.json()
      ]);''',
"Parse")

        text = rep(text,
'''      if (snowData.metric !== "shk_high") {
        throw new Error("Schnee-Parameter fehlt");
      }

      setupControls();''',
'''      if (snowData.metric !== "shk_high") {
        throw new Error("Schnee-Parameter fehlt");
      }
      if (!Array.isArray(pressureData.areas) || pressureData.areas.length !== 17) {
        throw new Error("Luftdruck-Gebietsliste unvollständig");
      }
      if (!Array.isArray(pressureData.periods) || pressureData.periods.length !== 36) {
        throw new Error("Luftdruck-Dekadenliste unvollständig");
      }
      if (!pressureData.metrics?.p_high || !pressureData.metrics?.p_low) {
        throw new Error("Luftdruck-Parameter fehlen");
      }

      setupControls();''',
"Validierung")

        text = rep(text,
'''      els.status.textContent =
        `DWD · Temperatur bis ${formatDate(data.data_through)} · ` +
        `Schnee bis ${formatDate(snowData.data_through)} · ` +
        `${data.areas.length} Gebiete · ${data.periods.length} Dekaden`;''',
'''      els.status.textContent =
        `DWD · Temperatur bis ${formatDate(data.data_through)} · ` +
        `Schnee bis ${formatDate(snowData.data_through)} · ` +
        `Luftdruck bis ${formatDate(pressureData.data_through)} · ` +
        `${data.areas.length} Gebiete · ${data.periods.length} Dekaden`;''',
"Status")

    required = [
        'value="p_high"', 'value="p_low"', "PRESSURE_DATA_URL",
        "pressureData", "const timeText =", "escapeHtml(entry[4])",
        "escapeHtml(point.entry[4])", "QN-1-Rekordkandidaten",
        "pressureResponse"
    ]
    missing = [x for x in required if x not in text]
    if missing:
        raise RuntimeError("Fehlend: " + ", ".join(missing))

    if text != original:
        path.write_text(text, encoding="utf-8")
        print("Luftdruck-Frontend eingebaut.")
    else:
        print("Frontend bereits aktuell.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="dekadenrekorde.html")
    args = ap.parse_args()
    patch(Path(args.file))

if __name__ == "__main__":
    main()
