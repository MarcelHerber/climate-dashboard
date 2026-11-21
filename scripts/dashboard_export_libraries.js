/* Classic script: shared, on-demand export dependencies, same CDN versions. */
(function (root) {
  "use strict";
  const pending = new Map();
  function load(key, url, get) {
    if (get()) return Promise.resolve(get());
    if (pending.has(key)) return pending.get(key);
    const script = document.createElement("script");
    script.src = url;
    script.async = true;
    const task = new Promise((resolve, reject) => {
      script.onload = () => {
        const library = get();
        if (library) resolve(library);
        else reject(new Error(key + " konnte nicht initialisiert werden."));
      };
      script.onerror = () => reject(new Error(key + " konnte nicht geladen werden."));
    });
    const result = task.catch(error => {
      script.remove();
      throw error;
    }).finally(() => pending.delete(key));
    pending.set(key, result);
    document.head.appendChild(script);
    return result;
  }
  root.dashboardExportLibraries = {
    pdf: () => load("jsPDF", "https://cdn.jsdelivr.net/npm/jspdf@4.2.1/dist/jspdf.umd.min.js", () => root.jspdf?.jsPDF),
    canvas: () => load("html2canvas", "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js", () => root.html2canvas),
  };
})(window);
