(() => {
  'use strict';
  const root = document.getElementById('snowMaps');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const dateSelect = $('snowMapDate');
  const status = $('snowMapStatus');
  const base = new URL('eurasia_snow/maps/', document.baseURI);
  const sources = [base, new URL('https://raw.githubusercontent.com/MarcelHerber/climate-dashboard/main/eurasia_snow/maps/')];
  const formatDate = value => new Intl.DateTimeFormat('de-DE', {timeZone:'UTC', dateStyle:'long'}).format(new Date(value + 'T00:00:00Z'));
  let records = [], selected = -1, active = null, imageBase = base, selectionToken = 0, loadToken = 0, sourceErrors = 0;

  function show(text, kind = 'normal') {
    status.textContent = text;
    status.dataset.kind = kind;
  }
  function controls(busy) {
    root.dataset.loading = String(busy);
    dateSelect.disabled = !records.length;
    $('snowMapPrevious').disabled = selected >= records.length - 1 || selected < 0;
    $('snowMapNext').disabled = selected <= 0;
    $('snowCoverDownload').disabled = busy || !active;
    $('snowAnomalyDownload').disabled = busy || !active;
  }
  async function request(url) {
    const response = await fetch(url, {cache:'no-cache', signal:AbortSignal.timeout(25000)});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response;
  }
  function preload(url) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      const timeout = setTimeout(() => reject(new Error('Kartenbild lädt zu lange')), 30000);
      image.onload = () => {clearTimeout(timeout); resolve(image);};
      image.onerror = () => {clearTimeout(timeout); reject(new Error('Kartenbild nicht verfügbar'));};
      image.src = url;
    });
  }
  function validRecord(row) {
    if (!row || !/^\d{4}-\d{2}-\d{2}$/.test(row.date)) return false;
    if (!Number.isFinite(Date.parse(row.date + 'T00:00:00Z'))) return false;
    return ['cover', 'anomaly'].every(key => row[key] === 'images/' + row.date + '_' + key + '.png');
  }
  function report(row) {
    const age = (Date.now() - Date.parse(row.valid_utc || row.date + 'T00:00:00Z')) / 86400000;
    let text = 'Gültig: ' + formatDate(row.date) + ', 00 UTC · NOAA IMS · Referenz 2001–2020';
    if (age >= 4) text += ' · Archivkarte, keine aktuellen Beobachtungen für dieses Datum.';
    if (sourceErrors) text += ' · Einzelne Quellen fehlen; verfügbarer Datenstand wird angezeigt.';
    show(text, age >= 4 || sourceErrors ? 'warn' : 'success');
    const years = Array.isArray(row.reference_years) ? row.reference_years : [];
    $('snowMapReference').textContent = 'Nordhalbkugel nördlich 20° N · ' +
      'Vergleich: gleicher Kalendertag 2001–2020 · ' + years.length + ' verfügbare Vergleichsjahre' +
      ' · mindestens ' + (row.minimum_samples || 15) + ' Landwerte je Rasterzelle.';
  }
  async function select(index) {
    const row = records[index];
    if (!row) return;
    const token = ++selectionToken;
    selected = index;
    dateSelect.value = row.date;
    active = null;
    controls(true);
    show('Schneekarten für ' + formatDate(row.date) + ' werden geladen …');
    try {
      const urls = ['cover', 'anomaly'].map(key => new URL(row[key], imageBase).href);
      await Promise.all(urls.map(preload));
      if (token !== selectionToken) return;
      for (const [i, key] of ['snowCoverImage', 'snowAnomalyImage'].entries()) {
        $(key).src = urls[i];
        $(key).hidden = false;
        $(key).alt = (i === 0 ? 'Beobachtete Schneebedeckung' : 'Abweichung von der Schneehäufigkeit 2001–2020') +
          ' · Nordhalbkugel · ' + formatDate(row.date) + ', 00 UTC';
      }
      active = {row, urls};
      report(row);
    } catch (error) {
      if (token !== selectionToken) return;
      for (const id of ['snowCoverImage', 'snowAnomalyImage']) $(id).hidden = true;
      show('Die Karten für ' + formatDate(row.date) + ' konnten nicht geladen werden. Bitte erneut versuchen oder ein anderes Datum wählen.', 'warn');
    } finally {
      if (token === selectionToken) controls(false);
    }
  }
  async function load() {
    const token = ++loadToken;
    ++selectionToken; // Invalidate in-flight images when a new manifest is requested.
    active = null;
    controls(true);
    show('Verfügbare IMS-Schneekarten werden geprüft …');
    $('snowMapRefresh').disabled = true;
    try {
      let doc = null, source = null;
      for (const candidate of sources) {
        try {
          const data = await (await request(new URL('index.json', candidate))).json();
          if (data.schema !== 1 || !Array.isArray(data.maps) || !data.maps.length ||
              !data.maps.every(validRecord) || data.reference_period?.join('-') !== '2001-2020') throw new Error('Ungültiges Kartenverzeichnis');
          doc = data; source = candidate; break;
        } catch (error) { /* Try the independently published raw data source. */ }
      }
      if (token !== loadToken) return;
      if (!doc) throw new Error('Kein Kartenverzeichnis');
      const oldDate = dateSelect.value;
      records = [...doc.maps].sort((a, b) => b.date.localeCompare(a.date));
      imageBase = source;
      sourceErrors = doc.source_errors?.length || 0;
      dateSelect.replaceChildren(...records.map(row => new Option(formatDate(row.date) + ' · 00 UTC', row.date)));
      const oldIndex = records.findIndex(row => row.date === oldDate);
      await select(oldIndex >= 0 ? oldIndex : 0);
    } catch (error) {
      if (token !== loadToken) return;
      for (const id of ['snowCoverImage', 'snowAnomalyImage']) $(id).hidden = true;
      records = []; selected = -1;
      dateSelect.replaceChildren(new Option('Keine Karten verfügbar', ''));
      show('IMS-Schneekarten sind momentan nicht erreichbar. Bitte Karten aktualisieren. Die Eurasien-Zeitreihe kann unabhängig davon genutzt werden.', 'warn');
      controls(false);
    } finally {
      if (token === loadToken) $('snowMapRefresh').disabled = false;
    }
  }
  async function download(kind) {
    if (!active) return;
    const selection = active;
    const button = $(kind === 'cover' ? 'snowCoverDownload' : 'snowAnomalyDownload');
    button.disabled = true;
    try {
      const response = await request(selection.urls[kind === 'cover' ? 0 : 1]);
      const blob = await response.blob();
      if (!blob.type.startsWith('image/')) throw new Error('Keine Bilddatei');
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url;
      link.download = 'NOAA_IMS_Nordhalbkugel_' + (kind === 'cover' ? 'Schneebedeckung_' : 'Abweichung_2001-2020_') + selection.row.date + '.png';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (error) {
      show('Der PNG-Download ist fehlgeschlagen. Bitte erneut versuchen.', 'warn');
    } finally {
      controls(!active);
    }
  }
  dateSelect.addEventListener('change', () => select(records.findIndex(row => row.date === dateSelect.value)));
  $('snowMapPrevious').addEventListener('click', () => select(selected + 1));
  $('snowMapNext').addEventListener('click', () => select(selected - 1));
  $('snowMapRefresh').addEventListener('click', load);
  $('snowCoverDownload').addEventListener('click', () => download('cover'));
  $('snowAnomalyDownload').addEventListener('click', () => download('anomaly'));
  root.addEventListener('keydown', event => {
    if (event.target.tagName === 'SELECT' || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'ArrowLeft' && selected < records.length - 1) {event.preventDefault(); select(selected + 1);}
    if (event.key === 'ArrowRight' && selected > 0) {event.preventDefault(); select(selected - 1);}
  });
  load();
})();
