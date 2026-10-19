const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const file=path.join(__dirname,'../dist/model.js');
const M=fs.existsSync(file)?require(file):{};
test('relative reference is subtracted once and converted with repository constants',()=>{
  assert.equal(typeof M.relativeEnergy,'function','energy model is missing');
  assert.ok(Math.abs(M.relativeEnergy(-100,-100.01,'kcal')-6.2750947406)<1e-7);
  assert.equal(M.relativeEnergy(-100,-100,'kj'),0);
});
test('direct difference never subtracts the reference again',()=>{
  assert.equal(typeof M.relativeEnergy,'function');
  assert.equal(M.relativeEnergy(.01,-100,'eh','direct'),.01);
});
test('missing or nonfinite energy is unavailable rather than zero',()=>{
  assert.equal(typeof M.relativeEnergy,'function');
  for(const value of [null,undefined,NaN,Infinity]) assert.equal(M.relativeEnergy(value,-100,'kcal'),null);
  assert.equal(M.relativeEnergy(-100,null,'kcal'),null);
  assert.equal(M.relativeEnergy(-100,-100,'unknown'),null);
});
test('stage requires source, role and positive composition',()=>{
  assert.equal(typeof M.validateStage,'function');
  assert.equal(M.validateStage({role:'TS',species:['ts'],coefficient:1}).valid,true);
  assert.equal(M.validateStage({role:'TS',species:[],coefficient:1}).valid,false);
  assert.equal(M.validateStage({role:'',species:['r'],coefficient:0}).valid,false);
});
test('corrupt or unknown progress falls back to safe known chapters',()=>{
  assert.equal(typeof M.readProgress,'function');
  assert.deepEqual(M.readProgress('{bad',['home']),{done:[],last:'home'});
  assert.deepEqual(M.readProgress('{"done":["home","fake","home"],"last":"fake"}',['home']),{done:['home'],last:'home'});
  assert.deepEqual(M.readProgress('null',['home']),{done:[],last:'home'});
});
test('CSV escapes source text and spreadsheet formulas',()=>{
  assert.equal(typeof M.csv,'function');
  const result=M.csv([['label','energy'],['a,"b',2],['=SUM(A1)',0]]);
  assert.ok(result.includes('"a,""b"'));
  assert.ok(result.includes("'=SUM(A1)"));
});
test('barrier requires an explicit TS and a distinct precursor',()=>{
  assert.equal(typeof M.barrier,'function');
  assert.ok(M.barrier({role:'TS',energy:-99.98,id:'t'},{role:'R',energy:-100,id:'r'},'kcal')>12);
  assert.equal(M.barrier({role:'I',energy:-99.98,id:'t'},{role:'R',energy:-100,id:'r'},'kcal'),null);
});
test('restarting a chart or table preserves saved scientific settings',()=>{
  assert.equal(typeof M.withSavedScience,'function');
  const base={kind:'scf',reference:'none',unit:'kcal',selected:'r'};
  const saved={kind:'g',reference:'r',unit:'eh',projectName:'Example'};
  for(const id of ['profile','tables'])assert.deepEqual(M.withSavedScience(base,saved,id),{kind:'g',reference:'r',unit:'eh',selected:'r'});
  assert.deepEqual(M.withSavedScience(base,saved,'energy'),base);
});
test('the same TS source supplies chart, thermal correction and log evidence',()=>{
  assert.ok(Array.isArray(M.exampleNodes),'shared source data is missing');
  const ts=M.exampleNodes.find(n=>n.id==='ts'),e=M.exampleEvidence;
  assert.equal(e.source,ts.source);
  assert.equal(e.scf,ts.energy);
  assert.equal(e.g,ts.g);
  assert.ok(Math.abs(e.scf+e.correction-e.g)<1e-12);
  assert.equal(e.scf,-99.966);
  assert.equal(e.g,-99.921);
});
