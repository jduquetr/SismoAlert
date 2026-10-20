// Exercise browser connection lifecycle with controllable transport and time.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const source = html.slice(html.indexOf('let lastBeat = 0;'), html.indexOf('async function activateAudio()'));
let now = 100000, watchdog;
const streams = [], rendered = [], updates = [];
class FakeSource {
  constructor() { this.handlers = {}; this.closed = false; streams.push(this); }
  addEventListener(type, fn) { this.handlers[type] = fn; }
  close() { this.closed = true; }
  stations(data = []) { this.handlers.stations({data: JSON.stringify(data)}); }
}
const c = { Date:{now:()=>now}, EventSource:FakeSource, isSnapshot:false,
  connectionState:'loading', hasState:false, stateLoaded:true, stateRetry:null,
  setInterval(fn) { watchdog = fn; }, clearTimeout(){},
  setConnection(state) { c.connectionState=state; }, showDataNotice(){},
  load(){}, drawStations(){}, tickClock(){}, toast(){}, addLog(){},
  renderStations(data){rendered.push(data);}, handleDet(data){updates.push(data);}
};
vm.createContext(c); vm.runInContext(source,c);
c.connect();
const first=streams[0]; first.onopen(); first.stations([{station:'HEL'}]);
assert.equal(c.connectionState,'live');
now += 21000; watchdog();
assert.equal(streams.length,2,'a stream that silently stalls must be replaced');
assert.equal(first.closed,true,'old connection must be closed before replacement');
const second=streams[1]; second.onopen();
assert.notEqual(c.connectionState,'live','HTTP connection alone does not prove station updates');
first.stations([{station:'OLD'}]);
first.handlers.detection({data:JSON.stringify({id:'old'})});
first.onerror();
assert.equal(rendered.length,1,'late packets from a replaced stream must be ignored');
assert.equal(updates.length,0,'replaced streams must not announce detections');
second.stations([{station:'HEL'}]); assert.equal(c.connectionState,'live');
now += 15000; second.stations(); now += 10000; watchdog();
assert.equal(streams.length,2,'healthy station updates keep the connection open');
second.onerror(); assert.equal(c.connectionState,'offline');
now += 11000; watchdog();
assert.equal(streams.length,3,'terminal errors must eventually reconnect');
const third=streams[2];
c.connect(true);
assert.equal(third.closed,true,'manual reconnection also closes the old stream');
const fourth=streams[3];
now += 21000; watchdog();
assert.equal(fourth.closed,true,'a connection that never opens must also time out');
const resume=html.match(/function resumeConnection\(\) \{[^]*?\n\}/)[0];
c.document={hidden:false};c.PAGE_TITLE='SismoAlert';
let loads=0;c.load=()=>loads++;
vm.runInContext(resume,c);
streams.at(-1).stations();
const healthyCount=streams.length;
c.resumeConnection();
assert.equal(streams.length,healthyCount,'resuming a healthy page does not duplicate streams');
assert.equal(loads,1,'resuming refreshes the snapshot');
now+=21000;c.document.hidden=true;c.resumeConnection();
assert.equal(streams.length,healthyCount,'hidden-page changes do not reconnect');
c.document.hidden=false;c.resumeConnection();
assert.equal(streams.length,healthyCount+1,'returning from sleep restores a stale stream');
const before=streams.length;
c.isSnapshot=true; c.SNAPSHOT_TAKEN='2026-10-20T12:00:00Z'; c.fmtTime=x=>x;
watchdog(); c.connect();
assert.equal(streams.length,before,'historical copies never open live connections');
console.log('OK: silent stall, late events, freshness, errors, manual retry, opening timeout, sleep recovery and snapshot isolation');
