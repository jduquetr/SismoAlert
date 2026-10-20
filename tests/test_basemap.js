// Regression: a successful tile response can still contain an API-key watermark.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
function source(name) {
  const match = html.match(new RegExp('function ' + name + '\\([^]*?\\n\\}'));
  assert.ok(match, name); return match[0];
}
let saved = null;
const context = {
  BASE_MAP_KEY: 'sismos-mapa-base', isSnapshot: false,
  localStorage: {getItem: () => saved, setItem: (_, value) => { saved = value; }},
  L: {tileLayer: (url, options) => ({url, options})},
};
vm.createContext(context);
vm.runInContext(source('baseLayers') + '\n' + source('initialBaseMap'), context);
const layers = context.baseLayers();
for (const oldPreference of [null, 'Claro · CARTO', 'Oscuro · CARTO', 'removed-layer', '__proto__']) {
  saved = oldPreference;
  assert.equal(context.initialBaseMap(layers), 'Calles · OpenStreetMap');
  assert.equal(saved, 'Calles · OpenStreetMap', 'replace the saved unavailable layer');
}
saved = 'Satélite · Esri';
assert.equal(context.initialBaseMap(layers), saved, 'preserve an available selection');
assert.equal(layers['Calles · OpenStreetMap'].url, 'https://tile.openstreetmap.org/{z}/{x}/{y}.png');
assert.match(layers['Calles · OpenStreetMap'].options.attribution, /https:\/\/www.openstreetmap.org\/copyright/);
assert.ok(Object.values(layers).every(layer => !layer.url.includes('cartocdn.com')), 'no unauthenticated CARTO tiles');
context.isSnapshot = true; saved = 'Claro · CARTO';
assert.equal(context.initialBaseMap({...layers, 'Contornos · sin conexión': {}}), 'Contornos · sin conexión');
context.isSnapshot = false;
context.localStorage = {getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); }};
assert.equal(context.initialBaseMap(layers), 'Calles · OpenStreetMap', 'blocked storage must not disable the map');
// Theme changes must not put a retired provider back on the map.
const button = {};
context.$ = () => button;
context.document = {documentElement: {dataset: {theme: 'light'}}};
context.applyTheme = theme => { context.document.documentElement.dataset.theme = theme; };
context.mapLayers = layers;
context.currentBaseLayer = layers['Calles · OpenStreetMap'];
context.map = {removeLayer() { throw Error('Theme replaced the base map'); }};
const start = html.indexOf('$("#theme").onclick = () => {');
vm.runInContext(html.slice(start, html.indexOf('\n};', start) + 3), context);
button.onclick(); assert.equal(context.document.documentElement.dataset.theme, 'dark');
button.onclick(); assert.equal(context.document.documentElement.dataset.theme, 'light');
console.log('OK: key-free default, retired preference migration, offline snapshot, attribution, blocked storage and theme changes');
