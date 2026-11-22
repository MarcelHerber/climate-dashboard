const fs = require('node:fs');
const path = require('node:path');

// Include classic dashboard modules in document order for source-level assertions.
module.exports = function dashboardSource() {
  const root = path.join(__dirname, '..');
  let html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  // Reconstruct the thematic source order for static assertions, including
  // modules referenced by the dynamic loader rather than by HTML tags.
  if (html.includes('src="js/loader.js')) {
    const loader = fs.readFileSync(path.join(root, 'js/loader.js'), 'utf8');
    if (loader.includes('const MODULES=')) {
      for (const match of loader.matchAll(/"([^"]+)":\["([^"]+\.js)","([^"]+)"\]/g)) {
        const [,name,src,version]=match;
        const tag='<script src="'+src+'?v='+version+'"></script>\n';
        if(src.startsWith('js/')) {
          const anchor=name==='schnee'?'export-karten-vergleich':name==='hyras-tmin'?'bootstrap':'dashboard-state';
          html=html.replace('<script src="js/'+anchor+'.js',tag+'<script src="js/'+anchor+'.js');
        } else html=html.replace('</head>',tag+'</head>');
      }
    } else {
    for (const [anchor, modules] of [
      ['export-karten-vergleich', ['schnee']],
      ['dashboard-state', ['aktuell', 'era5-land', 'europa-stationen']],
    ]) {
      html = html.replace('<script src="js/' + anchor + '.js', modules.map(name =>
        '<script src="js/' + name + '.js"></script>').join('\n') + '\n<script src="js/' + anchor + '.js');
    }
    }
  }
  return html.replace(
    /<script src="(js\/[\w.-]+\.js)(?:\?[^\"]*)?"><\/script>/g,
    (tag, src) => tag + '\n' + fs.readFileSync(path.join(root, src), 'utf8') + '\n'
  );
};
