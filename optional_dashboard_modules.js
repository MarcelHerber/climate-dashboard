/* Dashboard optional modules: on-demand JS, identical scientific data sources.
   Keep existing tabs and navigation reachable before heavy modules initialize. */
(function () {
  "use strict";
  const scripts = {
    mosmix: "mosmix.js?v=20261117-export-visible",
    thresholds: "station_thresholds.js?v=20261103-white-export-v2",
    frequency: "monthly_frequency.js?v=20261113-phase2-exports-v1"
  };
  const pending = new Map();
  const finished = new Set();

  function report(name, error) {
    const text = name + " konnte nicht geladen werden: " + error.message;
    console.error("[Dashboard-Lazy] " + text, error);
    const targets = {
      mosmix: "mosmixLazyStatus",
      thresholds: "stationClimateDaysSummary",
      frequency: "monthlyFrequencyLazyStatus"
    };
    const target = document.getElementById(targets[name]);
    if (target) {
      if (name === "thresholds") {
        const note = document.createElement("p");
        note.className = "note";
        note.textContent = text;
        target.appendChild(note);
      } else target.textContent = text;
    }
  }

  function load(name) {
    if (finished.has(name)) return Promise.resolve(true);
    if (pending.has(name)) return pending.get(name);
    const promise = new Promise(resolve => {
      const tag = document.createElement("script");
      tag.src = scripts[name];
      tag.async = true;
      tag.dataset.dashboardOptional = name;
      tag.onload = () => {
        finished.add(name);
        resolve(true);
      };
      tag.onerror = () => {
        report(name, new Error("Lokale Datei " + scripts[name] + " nicht erreichbar"));
        resolve(false);
      };
      document.head.appendChild(tag);
    }).then(ok => {
      pending.delete(name);
      return ok;
    });
    pending.set(name, promise);
    return promise;
  }

  function ensureMosmixEntry() {
    if (!document.getElementById("mosmix")) {
      const parent = document.querySelector(".dashboard-main") || document.body;
      const tab = document.createElement("div");
      tab.id = "mosmix";
      tab.className = "tab-content";
      tab.dataset.mosmixLazyShell = "1";
      tab.innerHTML = '<div class="section-header"><h2>DWD MOSMIX</h2></div>' +
        '<p id="mosmixLazyStatus" class="note" role="status">MOSMIX wird beim Öffnen geladen …</p>';
      const footer = parent.querySelector(".dashboard-footer");
      if (footer) parent.insertBefore(tab, footer);
      else parent.appendChild(tab);
    }

    const menu = document.querySelector('.nav-dropdown[data-nav-group="germany"] .nav-dropdown-menu');
    if (menu && !menu.querySelector('[data-mosmix-nav="1"]')) {
      const divider = document.createElement("div");
      divider.className = "nav-menu-divider";
      divider.dataset.mosmixNav = "1";
      const heading = document.createElement("div");
      heading.className = "nav-menu-heading";
      heading.textContent = "Vorhersage";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tab-button";
      button.dataset.navGroup = "germany";
      button.dataset.mosmixNav = "1";
      button.textContent = "DWD MOSMIX";
      button.setAttribute("onclick", "switchTab('mosmix')");
      button.addEventListener("click", () => { void loadMosmix(); });
      menu.appendChild(divider);
      menu.appendChild(heading);
      menu.appendChild(button);
    }

    const selector = document.querySelector(".mobile-tab-navigation select");
    if (selector && !selector.querySelector('option[value="mosmix"]')) {
      const option = document.createElement("option");
      option.value = "mosmix";
      option.textContent = "DWD MOSMIX";
      selector.appendChild(option);
      selector.addEventListener("change", () => {
        if (selector.value === "mosmix") void loadMosmix();
      });
    }
  }

  function loadMosmix() {
    return load("mosmix").then(ok => {
      if (ok) window.ensureMosmixDashboardInit?.();
      return ok;
    });
  }
  function loadThresholds() {
    return load("thresholds");
  }
  function loadMonthlyFrequency() {
    return load("frequency");
  }

  // Run synchronously at the foot of index.html so persisted MOSMIX tab
  // selection sees its shell before DOMContentLoaded restores dashboard state.
  ensureMosmixEntry();
  window.DashboardOptionalModules = {
    loadMosmix, loadThresholds, loadMonthlyFrequency,
    loaded: name => finished.has(name)
  };
  document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("mosmix")?.classList.contains("active")) {
      void loadMosmix();
    }
  }, { once: true });
})();
