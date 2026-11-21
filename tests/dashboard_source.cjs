const fs = require('node:fs');
const path = require('node:path');

// Include classic dashboard modules in document order for source-level assertions.
module.exports = function dashboardSource() {
  const root = path.join(__dirname, '..');
  let html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  // Reconstruct the thematic source order for static assertions, including
  // modules referenced by the dynamic loader rather than by HTML tags.
  if (html.includes('src="js/loader.js')) {
    for (const [anchor, modules] of [
      ['export-karten-vergleich', ['schnee']],
      ['dashboard-state', ['aktuell', 'era5-land', 'europa-stationen']],
    ]) {
      html = html.replace('<script src="js/' + anchor + '.js', modules.map(name =>
        '<script src="js/' + name + '.js"></script>').join('\n') + '\n<script src="js/' + anchor + '.js');
    }
  }
  return html.replace(
    /<script src="(js\/[\w.-]+\.js)(?:\?[^\"]*)?"><\/script>/g,
    (tag, src) => tag + '\n' + fs.readFileSync(path.join(root, src), 'utf8') + '\n'
  );
};
