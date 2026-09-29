// Comprobaciones sin navegador ni red de los estados nuevos del servidor.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) {
  new vm.Script(match[1]);
}
const source = html.match(/function catalogStatus\(d\) \{[\s\S]*?\n\}/)[0];
const context = {esc: s => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;')};
vm.createContext(context);
vm.runInContext(source, context);
assert.match(context.catalogStatus({search: 'buscando'}), /habilitados/);
assert.match(context.catalogStatus({search: 'error'}), /incompleta/);
assert.match(context.catalogStatus({search: 'terminada', catalog_status: {SGC: 'error'}}), /incompleta: SGC/);
assert.match(context.catalogStatus({search: 'terminada', catalog_status: {USGS: 'ok', EMSC: 'ok'}}), /Sin coincidencias/);
assert.doesNotMatch(context.catalogStatus({search: 'terminada'}), /falsa alarma/);
assert.match(context.catalogStatus({search: 'descartada', discarded: 'gap'}), /cerrada/);
console.log('OK: scripts válidos y 6 comprobaciones de estado');
