// Alert behavior without contacting Telegram or creating OS notifications.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../static/index.html'), 'utf8');
const source = name => html.match(new RegExp('function '+name+'\\([^]*?\\n\\}'))[0];
const delivered = [], tones = [];
function Notification(title, options) { delivered.push({title, ...options}); }
Notification.permission = 'granted';
const ctx = {Date, Notification, window:{Notification}, document:{title:''}, notified:new Set(),
  dets:new Map(), liveVersions:new Map(), liveRevision:0, selectedId:null,
  renderDets(){},autoSimulate(){},toast(){},beep:level=>tones.push(level)};
vm.createContext(ctx);
vm.runInContext(['notify','handleDet','rememberNotifications'].map(source).join('\n'),ctx);
const det = {id:'TEST-LOCAL',first_onset:'2026-10-20T12:00:00Z',level:'baja',message:'Prueba aislada',stations:{}};
const info = {...det,catalog:{EMSC:{id:'same-event',mag:4.5,priority:'informativa',place:'Prueba',distance_km:300,depth:10}}};
const critical = {...det,catalog:{EMSC:{...info.catalog.EMSC,priority:'crítica',distance_km:50}}};
ctx.handleDet(det,'detection'); ctx.handleDet(det,'update');
assert.equal(delivered.length,1,'same detection must not repeat');
ctx.handleDet({...det,level:'alta'},'update');
assert.equal(delivered.length,2,'rising detector level must alert');
ctx.handleDet(info,'catalog'); ctx.handleDet(info,'catalog');
assert.equal(delivered.length,3,'first catalogue alert appears once');
ctx.handleDet(critical,'catalog');
assert.equal(delivered.length,4,'critical revision of the same event and magnitude must alert');
assert.equal(tones.at(-1),'crítica');
ctx.handleDet(critical,'catalog'); ctx.handleDet(info,'catalog');
assert.equal(delivered.length,4,'duplicates and lower priorities must not re-alert');
ctx.handleDet({...critical,discarded:'artefacto'},'catalog');
assert.equal(delivered.length,4,'discarded events must not notify');
ctx.notified.clear(); delivered.length=0;
ctx.rememberNotifications(info); ctx.handleDet(info,'catalog');
assert.equal(delivered.length,0,'reconnection must not replay a known catalogue alert');
ctx.handleDet(critical,'catalog');
assert.equal(delivered.length,1,'critical revision after reconnection must alert');
Notification.permission='denied';
ctx.handleDet({...det,id:'DENIED'},'detection');
assert.equal(delivered.length,1,'denied permissions must not create a notification');
assert.equal(tones.at(-1),'baja','in-page audio remains independent of OS permission');
const scheduled = [];
ctx.volume=60;
ctx.audio={currentTime:10,destination:{},
  createOscillator:()=>({frequency:{},connect:()=>({connect(){}}),start:at=>scheduled.push(at),stop(){}}),
  createGain:()=>({gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}}})};
vm.runInContext(source('beep'),ctx);
ctx.beep('crítica'); assert.equal(scheduled.length,3,'critical sound has three pulses');
ctx.beep('media'); assert.equal(scheduled.length,4,'medium sound has one pulse');
ctx.volume=0; ctx.beep('alta'); assert.equal(scheduled.length,4,'zero volume is silent');
ctx.audio=null; ctx.volume=60; ctx.beep('alta'); assert.equal(scheduled.length,4,'audio is not implicitly enabled');
console.log('OK: detection escalation, critical catalogue revisions, deduplication, discarded events, reconnect, notification denial and audio patterns');
