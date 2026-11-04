/* Clickable, accessible dataset and band visibility controls for stratosphaere.html.
   Chart.js source arrays remain unchanged. A two-dataset filled interval is
   treated as one item so hiding its lower boundary never alters the fill.
*/
(() => {
  'use strict';
  if (typeof Chart === 'undefined' || typeof Chart.register !== 'function') return;

  const preferences = new Map();
  const viewPanels = new WeakMap();

  function labelOf(source) {
    let name = String(source || '').replace(/^_+/, '').replace(/\s+(?:Untergrenze|min|max)$/i, '').trim();
    if (/^\d+%$/.test(name)) name = 'Perzentilfläche ' + name;
    return name || 'Linie';
  }
  function colorOf(dataset) {
    const fill = dataset.fill;
    if (fill && typeof fill === 'object' && fill.above) return fill.above;
    const candidates = [dataset.borderColor, dataset.backgroundColor].flat();
    return candidates.find(c => typeof c === 'string' &&
      !/^(?:transparent|rgba\(\s*0,\s*0,\s*0,\s*0\s*\))$/i.test(c)) || '#64748b';
  }
  function isMember(dataset, label) {
    return /^_/.test(String(dataset.label || '')) &&
      /^(?:GEFS[_ ]|EPS[_ ]|p\d{2}\b|c\d{2}\b|member|Mitglied)/i.test(label);
  }
  function groups(chart) {
    const datasets = chart.data?.datasets || [], result = [], occurrences = new Map();
    for (let i = 0; i < datasets.length; i++) {
      const lower = datasets[i], upper = datasets[i + 1];
      const paired = upper && upper.fill && typeof upper.fill === 'object' &&
        String(upper.fill.target) === '-1';
      const indexes = paired ? [i, i + 1] : [i];
      const view = paired ? upper : lower;
      if (!indexes.some(index => Array.isArray(datasets[index].data) &&
        datasets[index].data.some(value => value !== null && value !== undefined))) {
        i += paired ? 1 : 0;
        continue; // Blank helper datasets are not selectable traces.
      }
      const name = labelOf(view.label), repeats = occurrences.get(name) || 0;
      occurrences.set(name, repeats + 1);
      result.push({
        key: name + '|' + repeats,
        label: name,
        indexes,
        member: !paired && isMember(view, name),
        filled: paired || !!(view.fill && view.fill !== false),
        color: colorOf(view)
      });
      i += paired ? 1 : 0;
    }
    return result;
  }
  function store(chart) {
    const id = chart.canvas?.id;
    if (!id) return new Map();
    if (!preferences.has(id)) preferences.set(id, new Map());
    return preferences.get(id);
  }
  function setVisible(chart, group, visible) {
    store(chart).set(group.key, visible);
    for (const index of group.indexes) chart.setDatasetVisibility(index, visible);
  }
  function visible(chart, group) {
    return group.indexes.every(index => chart.isDatasetVisible(index));
  }
  function element(name, css, text) {
    const el = document.createElement(name);
    if (css) el.className = css;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function action(name, type, key, pressed) {
    const button = element('button', 'strato-series-button', name);
    button.type = 'button';
    button.dataset.action = type;
    if (key) button.dataset.key = key;
    if (pressed !== undefined) {
      button.setAttribute('aria-pressed', String(pressed));
      button.classList.toggle('is-off', !pressed);
    }
    return button;
  }
  function chip(chart, group) {
    const on = visible(chart, group), button = action(group.label, 'toggle', group.key, on);
    button.classList.add('strato-series-chip');
    button.title = (on ? 'Ausblenden: ' : 'Einblenden: ') + group.label;
    const swatch = element('span', 'strato-series-swatch');
    swatch.setAttribute('aria-hidden', 'true');
    swatch.style.borderColor = group.color;
    if (group.filled) swatch.style.backgroundColor = group.color;
    button.prepend(swatch);
    return button;
  }
  function render(chart, panel) {
    const all = groups(chart);
    const previouslyOpen = panel.querySelector('details.strato-series-members')?.open || false;
    panel._chart = chart;
    panel._groups = all;
    const header = element('div', 'strato-series-header');
    const heading = element('strong', '', 'Linien und Flächen');
    const description = element('span', '', 'Antippen zum Ein- oder Ausblenden');
    const buttons = element('div', 'strato-series-tools');
    buttons.append(action('Alle ein', 'all-on'), action('Alle aus', 'all-off'));
    header.append(heading, description, buttons);
    const regular = element('div', 'strato-series-chips');
    for (const group of all.filter(g => !g.member)) regular.append(chip(chart, group));
    const content = [header, regular];
    const members = all.filter(g => g.member);
    if (members.length) {
      const details = element('details', 'strato-series-members');
      details.open = previouslyOpen;
      const on = members.filter(g => visible(chart, g)).length;
      const summary = element('summary', '',
        'Einzelmitglieder (' + on + '/' + members.length + ' sichtbar) · einzeln auswählen');
      const controls = element('div', 'strato-series-tools');
      controls.append(action('Mitglieder ein', 'members-on'), action('Mitglieder aus', 'members-off'));
      const chips = element('div', 'strato-series-chips');
      for (const group of members) chips.append(chip(chart, group));
      details.append(summary, controls, chips);
      content.push(details);
    }
    panel.replaceChildren(...content);
  }
  function panelFor(chart) {
    if (viewPanels.has(chart)) return viewPanels.get(chart);
    const canvas = chart.canvas, wrapper = canvas?.parentElement;
    if (!wrapper || !canvas.id) return null;
    const panel = element('div', 'strato-series-panel');
    panel.setAttribute('role', 'group');
    panel.setAttribute('aria-label', 'Diagrammlinien und Flächen für ' + canvas.id);
    wrapper.insertAdjacentElement('afterend', panel);
    panel.addEventListener('click', event => {
      const button = event.target.closest?.('button[data-action]');
      if (!button || !panel.contains(button)) return;
      const current = panel._chart, all = panel._groups || [];
      if (!current) return;
      const type = button.dataset.action;
      if (type === 'toggle') {
        const target = all.find(group => group.key === button.dataset.key);
        if (target) setVisible(current, target, !visible(current, target));
      } else {
        const selected = type.startsWith('members-') ? all.filter(group => group.member) : all;
        const show = type === 'all-on' || type === 'members-on';
        for (const group of selected) setVisible(current, group, show);
      }
      current.update('none');
    });
    viewPanels.set(chart, panel);
    return panel;
  }
  const plugin = {
    id: 'stratoSeriesVisibility',
    beforeUpdate(chart) {
      // External controls leave more usable plot space than long Chart.js legends.
      if (chart.options?.plugins?.legend) chart.options.plugins.legend.display = false;
      const settings = store(chart);
      for (const group of groups(chart)) {
        const previous = settings.get(group.key);
        if (previous !== undefined) {
          for (const index of group.indexes) chart.setDatasetVisibility(index, previous);
        }
      }
    },
    afterUpdate(chart) {
      const panel = panelFor(chart);
      if (panel) render(chart, panel);
    },
    beforeDestroy(chart) {
      const panel = viewPanels.get(chart);
      if (panel) panel.remove();
      viewPanels.delete(chart);
    }
  };
  Chart.register(plugin);
  window.stratoSeriesVisibility = {groups, preferences};
})();
