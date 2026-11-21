const fs = require('node:fs');
const path = require('node:path');

// Include classic dashboard modules in document order for source-level assertions.
module.exports = function dashboardSource() {
  const root = path.join(__dirname, '..');
  return fs.readFileSync(path.join(root, 'index.html'), 'utf8').replace(
    /<script src="(js\/[\w.-]+\.js)(?:\?[^\"]*)?"><\/script>/g,
    (tag, src) => tag + '\n' + fs.readFileSync(path.join(root, src), 'utf8') + '\n'
  );
};
