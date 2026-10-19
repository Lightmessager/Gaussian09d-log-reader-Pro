const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
function loadVisuals(){
  // Only canvas/browser setup is stubbed; chart SVG is the real production output.
  const context={AcademyModel:require('../dist/model.js'),innerWidth:1440,innerHeight:900,devicePixelRatio:1,
    document:{getElementById:()=>({getContext:()=>({setTransform(){}})}),addEventListener(){}},
    window:{addEventListener(){}}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../dist/visuals.js'),'utf8'),context);
  return context.AcademyVisuals;
}
test('standalone glow path explicitly disables SVG default black fill',()=>{
  const svg=loadVisuals().chart();
  const glow=svg.match(/<path\b[^>]*class="curve-glow"[^>]*>/)?.[0];
  assert.ok(glow,'expected the real chart glow layer');
  assert.match(glow,/\bfill="none"/,'a detached SVG must not depend on webpage CSS to prevent black fill');
  assert.match(glow,/\bstroke-width="4"/);
  assert.match(glow,/\bopacity="0?\.35"/);
});
module.exports={loadVisuals};
