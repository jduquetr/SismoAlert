// Behavioral regressions for the dashboard; no network, browser permissions or alerts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
function code(name) {
  const re = new RegExp('(?:async )?function '+name+'\\([^]*?\\n\\}');
  const match = html.match(re); assert.ok(match, name); return match[0];
}
function setup(extra={}) {
  const controls = {'#search':{value:''}, '#filter-status':{value:'all'}, '#show-tests':{checked:false}};
  const c = {URL, AbortController, Date, setTimeout:()=>1, clearTimeout:()=>{}, console,
    $:s=>controls[s], controls, dets:new Map(), isSnapshot:false,
    connectionState:'live', lastStationsAt:Date.now(), ...extra};
  vm.createContext(c);
  vm.runInContext(['safeUrl','stationAge','stationAlive','visibleDetections','rememberNotifications'].map(code).join('\n'),c);
  return c;
}
(async()=>{
  const c=setup();
  assert.equal(c.safeUrl('javascript:alert(1)'),'#');
  assert.equal(c.safeUrl('data:text/html,hi'),'#');
  assert.equal(c.safeUrl('https://www.sgc.gov.co/a'),'https://www.sgc.gov.co/a');
  assert.equal(c.stationAlive({last_packet_age_s:undefined}),false);
  assert.equal(c.stationAlive({last_packet_age_s:null}),false);
  assert.equal(c.stationAlive({last_packet_age_s:10,latency_s:5}),true);
  assert.equal(c.stationAlive({last_packet_age_s:1,latency_s:700}),false,'new packets with old samples are not live data');
  assert.equal(c.stationAlive({last_packet_age_s:1,latency_s:null}),false);
  c.lastStationsAt=Date.now()-121000;
  assert.equal(c.stationAlive({last_packet_age_s:0,latency_s:0}),false);
  c.lastStationsAt=Date.now();c.connectionState='offline';
  assert.equal(c.stationAlive({last_packet_age_s:1,latency_s:1}),false);
  c.connectionState='live';c.isSnapshot=true;
  assert.equal(c.stationAlive({last_packet_age_s:1,latency_s:1}),false);
  c.isSnapshot=false;
  // Observation stations must be visibly distinguished, including absent signal.
  c.controls['#stations']={};c.controls['#station-coverage']={};
  c.document={activeElement:null};c.esc=String;c.fmtS=x=>`${x} s`;
  c.mapStations=()=>{};c.refreshSummary=()=>{};
  c.lastStations=[{station:'HEL',network:'CM',channel:'00.HHZ',alerts_enabled:true,last_packet_age_s:1,latency_s:5},
    {station:'TULM',network:'EC',channel:'HHZ',alerts_enabled:false,last_packet_age_s:1,latency_s:5}];
  vm.runInContext(code('drawStations'),c);c.drawStations();
  assert.match(c.controls['#station-coverage'].textContent,/1 estaciones del detector · 1 en observación/);
  assert.match(c.controls['#stations'].innerHTML,/class="st observation"[^]*Observación · sin alertas/);
  c.lastStations[1].latency_s=700;c.drawStations();
  assert.match(c.controls['#stations'].innerHTML,/TULM: Sin datos recientes. Observación · sin alertas/);
  const event={id:'a',first_onset:'2026-10-20T12:00:00Z',stations:{HEL:{}},catalog:{SGC:{place:'Istmina - Chocó',url:'https://www.sgc.gov.co/',id:'SGC1',mag:4.3,priority:'informativa'}}};
  c.dets.set('a',event);c.dets.set('b',{...event,id:'b',catalog:{}});c.dets.set('c',{...event,id:'c',test:true});c.dets.set('d',{...event,id:'d',discarded:'artefacto'});
  assert.equal(c.visibleDetections().length,3);
  c.controls['#search'].value='choco';assert.equal(c.visibleDetections().length,2);
  c.controls['#filter-status'].value='confirmed';assert.equal(c.visibleDetections().length,1);
  c.controls['#search'].value='HEL';c.controls['#filter-status'].value='pending';assert.equal(c.visibleDetections()[0].id,'b');
  c.controls['#filter-status'].value='discarded';assert.equal(c.visibleDetections()[0].id,'d');
  c.controls['#filter-status'].value='all';c.controls['#show-tests'].checked=true;assert.equal(c.visibleDetections()[0].id,'c');
  c.controls['#search'].value='inexistente';assert.equal(c.visibleDetections().length,0);
  const pending=[];
  const asyncContext=setup({loadController:null,liveRevision:0,stationsRevision:0,liveVersions:new Map(),notified:new Set(),hasState:false,stateLoaded:false,stateRetry:null,
    fetchJson:()=>new Promise(resolve=>pending.push(resolve)),renderStations:()=>{},renderDets:()=>{},addLog:()=>{},showDataNotice:()=>{}});
  vm.runInContext(code('load'),asyncContext);
  const request=asyncContext.load();
  const updated={...event,message:'newer SSE event'};
  asyncContext.liveVersions.set('a',1);asyncContext.liveRevision=1;asyncContext.dets.set('a',updated);
  pending.shift()({stations:[],log:[],detections:[event]});await request;
  assert.equal(asyncContext.dets.get('a').message,'newer SSE event','SSE newer than snapshot must win');
  const request2=asyncContext.load();
  pending.shift()({stations:[],log:[],detections:[event]});await request2;
  assert.ok(asyncContext.notified.has('a:SGC:SGC1:4.3:informativa'),'reconnection must seed catalogue notification deduplication');
  let notice='';asyncContext.fetchJson=async()=>{throw new Error('HTTP 500')};asyncContext.showDataNotice=s=>notice=s;
  await asyncContext.load();assert.match(notice,/No se pudo cargar/);
  // A local simulation must not reach fetch, notifications, Telegram, or real data counters.
  const controls={'#search':{},'#filter-status':{},'#show-tests':{},'#settings-dialog':{close:()=>{}}};
  const demo=setup({$:s=>controls[s],renderDets:()=>{},selectDet:()=>{},toast:()=>{},fetch:()=>{throw new Error('Unexpected network request')},notify:()=>{throw new Error('Unexpected notification')}});
  const start=html.indexOf('$("#test").onclick = () => {');
  const end=html.indexOf('\n};',start)+3;
  controls['#test']={};vm.runInContext(html.slice(start,end),demo);controls['#test'].onclick();
  assert.equal(demo.dets.size,1);assert.equal(demo.dets.get('PRUEBA-LOCAL').test,true);
  controls['#test'].onclick();assert.equal(demo.dets.size,1,'repeat demo must not accumulate duplicates');
  console.log('OK: freshness, filters, safe URLs, SSE race, reconnect deduplication, failure state and local-only demo');
})().catch(e=>{console.error(e);process.exitCode=1});
