(function(root){
  'use strict';
  const KJ=4.3597447222060e-18*6.02214076e23/1000;
  const factors={eh:1,kcal:KJ/4.184,kj:KJ};
  function relativeEnergy(value,reference,unit='kcal',mode='relative'){
    if(!Number.isFinite(value)||!factors[unit])return null;
    if(mode==='direct')return value*factors[unit];
    if(!Number.isFinite(reference))return null;
    return (value-reference)*factors[unit];
  }
  function validateStage(stage){
    const errors=[];
    if(!['R','I','TS','P'].includes(stage.role))errors.push('请选择阶段角色');
    if(!Array.isArray(stage.species)||!stage.species.length)errors.push('请加入至少一张已绑定来源的物质卡');
    if(!Number.isFinite(stage.coefficient)||stage.coefficient<=0)errors.push('组成系数必须大于 0');
    return {valid:!errors.length,errors};
  }
  function readProgress(raw,ids){
    const fallback={done:[],last:ids[0]};
    try{const p=JSON.parse(raw);if(!p||typeof p!=='object')return fallback;
      return {done:[...new Set(Array.isArray(p.done)?p.done.filter(id=>ids.includes(id)):[])],last:ids.includes(p.last)?p.last:ids[0]};
    }catch{return fallback;}
  }
  function csv(rows){return '\uFEFF'+rows.map(row=>row.map(cell=>{
    let s=String(cell??'');if(/^[\s]*[=+@-]/.test(s)&&typeof cell!=='number')s="'"+s;
    return '"'+s.replace(/"/g,'""')+'"';
  }).join(',')).join('\r\n');}
  function barrier(ts,precursor,unit='kcal'){
    if(!ts||!precursor||ts.role!=='TS'||ts.id===precursor.id)return null;
    return relativeEnergy(ts.energy,precursor.energy,unit);
  }
  function withSavedScience(base,saved,chapterId){
    return ['profile','tables'].includes(chapterId)?{...base,kind:saved.kind,reference:saved.reference,unit:saved.unit}:{...base};
  }
  const exampleNodes=[
    {id:'r',label:'R',role:'R',energy:-100,g:-99.95,source:'reactant.log',desc:'反应物'},
    {id:'i',label:'INT',role:'I',energy:-99.988,g:-99.936,source:'intermediate.log',desc:'中间体'},
    {id:'ts',label:'TS',role:'TS',energy:-99.966,g:-99.921,source:'transition.log',desc:'过渡态'},
    {id:'p',label:'P',role:'P',energy:-100.0076,g:-99.958,source:'product.log',desc:'产物'}
  ];
  const ts=exampleNodes.find(n=>n.id==='ts');
  const exampleEvidence={source:ts.source,scf:ts.energy,g:ts.g,correction:ts.g-ts.energy};
  const model={relativeEnergy,validateStage,readProgress,csv,barrier,factors,withSavedScience,exampleNodes,exampleEvidence};
  root.AcademyModel=model;
  if(typeof module!=='undefined')module.exports=model;
})(typeof globalThis!=='undefined'?globalThis:this);
