/* Protocol 2: render only. All energies, differences and label coordinates originate in Python. */
"use strict";
(() => {
const host = document.getElementById('plot');
const plot = document.createElement('div');plot.className='plotly-host';host.append(plot);
plot.style.width='100%';plot.style.height='100%';
let scene3d=null,sceneHost=null;
Plotly.register({moduleType:'locale',name:'zh-CN',dictionary:{'Zoom':'缩放','Pan':'平移','Box Select':'框选','Lasso Select':'套索选择',
 'Zoom in':'放大','Zoom out':'缩小','Autoscale':'自动范围','Reset axes':'重置坐标轴','Reset camera to default':'重置相机',
 'Reset camera to last save':'恢复相机','Orbit rotation':'旋转','Turntable rotation':'转台旋转','Toggle Spike Lines':'辅助线',
 'Show closest data on hover':'悬浮显示最近点','Compare data on hover':'悬浮比较数据'},format:{decimal:'.',thousands:','}});
let bridge = null, shown = null, pending = null, running = false, bound = false, syncing = false;
let annotations = [], renderCount = 0, compact = false, resizePending = false, resizeFrame = 0;
let cameraFlushTimer = 0;
const localViewports = {};
const esc = s => String(s == null ? '—' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const num = v => v == null ? '—' : Number(v).toPrecision(10);
const sameCamera = (a,b) => !!a&&!!b&&['eye','center','up'].every(k=>['x','y','z'].every(axis=>
  a[k]?.[axis]===b[k]?.[axis]||Math.abs(a[k]?.[axis]-b[k]?.[axis])<1e-7));
const isCompact = data => data.view==='3d'&&!data.image_capture&&plot.clientHeight<360;
function notify(type, data, payload = shown) {
  if(window.GRPR_STANDALONE&&type==='select'&&data.points?.length){const p=data.points.at(-1);window.GRPR_OFFLINE_ACTION({action:'select',...p,additive:data.additive});return;}
  if (bridge && payload) bridge.event(JSON.stringify({type, project_id:payload.project_id, revision:payload.revision, render_id:payload.render_id, ...data}));
}
function hover(p, path, data) {
  const t = data.text;
  const source = (p.dependencies || [])[0];
  const rows = [`<b>${esc(path.label)}</b> · ${esc(t.node)}: ${esc(p.label)}`,
    `<b>${esc(p.value_label)} ${esc(data.unit_label)}</b>`];
  if (data.mode === 'relative') {
    rows.push(`${esc(t.absolute)}: ${num(p.absolute_hartree)} Eh`);
    rows.push(`${esc(t.reference)}: ${esc(path.reference || '—')} · ${num(p.reference_hartree)} Eh`);
  } else if (data.mode === 'absolute') {
    rows.push(`${esc(t.absolute)}: ${num(p.absolute_hartree)} Eh`);
  }
  if (source) rows.push(`${esc(t.source)}: ${esc(source.source_label)} · ${esc(t.job)} ${esc((source.job_id || '').slice(0,8))} · ${esc(t.line)} ${esc(source.source_line)}`);
  if(p.starred_species?.length)rows.push(`★ ${p.starred_species.map(esc).join('、')}`);
  return rows.join('<br>');
}
let webglAvailable;
function webgl() {
  if(webglAvailable!==undefined)return webglAvailable;
  try { const c=document.createElement('canvas'),gl=c.getContext('webgl2');webglAvailable=!!gl;gl?.getExtension('WEBGL_lose_context')?.loseContext(); }
  catch(e) {webglAvailable=false;}return webglAvailable;
}
function tint(hex, amount) {
  const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
  return 'rgb('+rgb.map(v=>Math.round(v+(255-v)*amount)).join(',')+')';
}
function translucent(hex, opacity) {
  return 'rgba('+[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)).join(',')+','+opacity+')';
}
function ribbon(path, runs, depth, curtain=false) {
  const x=[],y=[],z=[],i=[],j=[],k=[];
  for(const run of runs){
    const start=x.length;
    for(const [step,value] of run){
      x.push(step,step);y.push(path.category-(curtain?0:.025),path.category+(curtain?0:.085));
      z.push(value,curtain?0:value-depth);
    }
    for(let n=0;n<run.length-1;n++){
      const a=start+2*n;i.push(a,a+1);j.push(a+1,a+3);k.push(a+2,a+2);
    }
  }
  return {type:'mesh3d',x,y,z,i,j,k,color:path.color,opacity:curtain?.035:.20,
    lighting:{ambient:1,diffuse:0,specular:0,roughness:1},flatshading:true,
    hoverinfo:'skip',showscale:false,showlegend:false,legendgroup:path.id,
    visible:path.visible?true:'legendonly',meta:{kind:curtain?'visual-curtain':'visual-ribbon'}};
}
function traces(data) {
  const all = [], labels = [], is3d = data.view === '3d';
  if (is3d && data.paths.length) {
    const steps=data.ticks.length?data.ticks:[0], categories=data.paths.filter(p=>p.visible).map(p=>p.category);
    if(!categories.length)categories.push(0);
    const x0=Math.min(...steps)-.35,x1=Math.max(...steps)+.35,y0=Math.min(...categories)-.45,y1=Math.max(...categories)+.45;
    all.push({type:'mesh3d',name:data.text.zero_plane,x:[x0,x1,x1,x0],y:[y0,y0,y1,y1],z:[0,0,0,0],
      i:[0,0],j:[1,2],k:[2,3],color:(data.visual_style||{}).zero||'#B9ACC9',opacity:.09,
      lighting:{ambient:1,diffuse:0,specular:0,roughness:1},flatshading:true,hoverinfo:'skip',showscale:false,
      showlegend:false,legendgroup:'zero-plane'});
  }
  const labelCount = data.paths.filter(p=>p.visible).reduce((n,p)=>n+p.points.length,0);
  const dense2d = !is3d && (plot.clientHeight < 360 || (plot.clientWidth < 1000 && data.paths.filter(p=>p.visible).length > 1));
  const style=data.visual_style||{},focus=style.focus||'#F4A06A';
  const depth=(data.default_y_range[1]-data.default_y_range[0])*.035;
  for (const path of data.paths) {
    const visible = path.visible ? true : 'legendonly';
    const x=[], y=[], z=[], px=[], py=[], pz=[],sx=[],sy=[],sz=[];
    const valid=path.points.filter(p=>p.valid && p.value != null);
    const selected=valid.filter(p=>p.selected);
    const runs=path.curve_runs||valid.map(p=>[[p.x,p.value]]);
    for(const run of runs){
      for(const [step,value] of run){x.push(step);y.push(is3d?path.category:value);z.push(value);}
      x.push(null);y.push(null);z.push(null);
    }
    for(const p of valid)if(is3d){
      if(p.selected){sx.push(p.x,p.x,null);sy.push(path.category,path.category,null);sz.push(p.value,0,null);}
      else{px.push(p.x,p.x,null);py.push(path.category,path.category,null);pz.push(p.value,0,null);}
    }
    const base={type:is3d?'scatter3d':'scatter',legendgroup:path.id,name:(is3d?String(path.category+1)+' · ':'')+esc(path.label)+' · '+esc(data.text.reference)+': '+esc(path.reference||'—'),visible,connectgaps:false};
    if(is3d){all.push(ribbon(path,runs,depth,true));all.push(ribbon(path,runs,depth));}
    for(const [width,opacity,kind] of [[is3d?20:18,data.dark?.07:.04,'curve-outer-glow'],
      [is3d?10:9,data.dark?.19:.10,'curve-inner-glow'],[is3d?5:3,1,'visual-curve']]){
      all.push({...base,mode:'lines',x,y,...(is3d?{z}:{}),line:{color:kind==='visual-curve'?tint(path.color,data.dark?.30:0):path.color,width},
        opacity,hoverinfo:'skip',showlegend:false,meta:{kind}});
    }
    if(is3d){
      all.push({...base,mode:'lines',x:px,y:py,z:pz,line:{color:path.color,width:1.5,dash:'dot'},
        opacity:.42,hoverinfo:'skip',showlegend:false,meta:{kind:'node-projection'}});
      all.push({...base,mode:'lines',x:sx,y:sy,z:sz,line:{color:focus,width:2.5,dash:'dot'},
        opacity:.9,hoverinfo:'skip',showlegend:false,meta:{kind:'selected-projection'}});
    }
    const halo=(points,size,color,opacity,kind,open=false)=>({...base,mode:'markers',x:points.map(p=>p.x),
      y:points.map(p=>is3d?path.category:p.value),...(is3d?{z:points.map(p=>p.value)}:{}),
      marker:{size,color,symbol:open?'circle-open':'circle',line:{color,width:open?2:0}},
      opacity,hoverinfo:'skip',showlegend:false,meta:{kind}});
    all.push(halo(valid,is3d?18:26,path.color,.12,'node-glow'));
    all.push(halo(selected,is3d?30:42,focus,.13,'selected-glow'));
    all.push(halo(selected,is3d?18:25,focus,1,'selected-ring',true));
    all.push({...base,mode:is3d?'markers+text':'markers',x:valid.map(p=>p.x),y:valid.map(p=>is3d?path.category:p.value),
      ...(is3d?{z:valid.map(p=>p.value),text:valid.map(p=>!compact&&(labelCount<=8||p.selected||p.role==='transition_state')?`<b>${p.starred_species?.length?'★ ':''}${esc(p.label_short)}</b><br>${esc(p.value_label)}`:''),textposition:'top center',textfont:{size:13,color:valid.map(p=>p.selected?focus:tint(path.color,.45))}}:{}),
      customdata:valid.map(p=>[path.id,p.entry_id,p.node_id,hover(p,path,data)]),
      marker:{size:valid.map(p=>is3d?(p.selected?11:8):(p.selected?16:12)),
        color:valid.map(p=>p.selected?focus:tint(path.color,data.dark?.24:0)),symbol:'circle',
        line:{color:data.dark?'#F4EFFA':'#FFFFFF',width:is3d?1:1.5}},
      meta:{kind:'computed-nodes'},
      hovertemplate:'%{customdata[3]}<extra></extra>',showlegend:true});
    if(!is3d && path.visible) for(const p of valid) if(labelCount<=40||p.selected||p.role==='transition_state') {
      if(dense2d&&path.id!==data.active_path_id&&!p.selected)continue;
      const range=data.viewport.y_range||data.default_y_range;
      const upper=p.value>range[0]+(range[1]-range[0])*.65;
      labels.push({path_id:path.id,entry_id:p.entry_id,x:p.x,y:p.value,
        ax:dense2d?Math.max(-48,Math.min(48,p.label_offset[0])):p.label_offset[0],
        ay:dense2d?Math.max(-84,Math.min(84,p.label_offset[1])):p.label_offset[1]});
    }
  }
  return {all,labels};
}
async function render(data) {
  document.body.style.pointerEvents=data.image_capture?'none':'';
  if(data.protocol_version!==2) throw new Error('Unsupported plot protocol');
  if(shown && data.project_id===shown.project_id && data.render_id<shown.render_id) return;
  window.replicaWorkbench?.update(data);
  let fallback = '';
  if(data.view==='3d' && (!webgl() || window.GRPR_FORCE_NO_WEBGL)) { data={...data,view:'2d'}; fallback=data.text.webgl; notify('webgl_fallback',{},data); }
  if(data.view==='3d'&&!window.GRPR_FORCE_PLOTLY){
    try {
      if(!scene3d){
        const {ProfileRenderer}=await (window.GRPR_MODULES?.scene||import('./scene3d.js'));
        sceneHost=document.createElement('div');sceneHost.className='scene-host';host.append(sceneHost);
        scene3d=new ProfileRenderer({
          select:(path,point,additive)=>window.grpr.selectPoint(path.id,point.entry_id,point.node_id,additive),
          context:(path,point)=>notify('species_select',{path_id:path.id,entry_id:point.entry_id,node_id:point.node_id}),
          viewport:(viewport)=>{if(shown?.view==='3d'){shown.viewport={...shown.viewport,...viewport};localViewports['3d']=shown.viewport;notify('view_state',{viewport});}},
          failed:reason=>{notify('webgl_fallback',{reason});enqueue({...shown,view:'2d'});}
        }).mount(sceneHost,document.getElementById('orientation-placeholder'));
      }
      plot.style.display='none';sceneHost.style.display='block';scene3d.setVisible(true);
      const same=shown?.view==='3d'&&['project_id','unit','kind','mode'].every(k=>shown[k]===data[k]);
      scene3d.setData(data);shown=data;renderCount++;
      // Reconcile an in-flight gesture against the newest guarded bridge envelope.
      if((same||data.viewport?.camera&&!data.viewport?.three_v1)&&JSON.stringify(data.viewport?.three_v1)!==JSON.stringify(scene3d.viewport()))scene3d.commit();
      const missing=data.paths.flatMap(p=>p.points.filter(n=>n.missing_transition_state).map(n=>`${n.label} · NOT FOUND`));
      document.getElementById('notice').textContent=[...data.warnings,...missing,scene3d.nodes.length?'':data.text.empty].filter(Boolean).join(' · ');
      if(bridge)bridge.rendered(JSON.stringify({project_id:data.project_id,revision:data.revision,render_id:data.render_id,view:'3d',
        points:data.paths.filter(p=>p.visible).flatMap(p=>p.points.filter(n=>n.valid&&n.value!=null).map(n=>({path_id:p.id,entry_id:n.entry_id,node_id:n.node_id,value:n.value}))),
        ...scene3d.diagnostics(),capabilities:['three_v1','plotly-v1'],render_count:renderCount,listeners_bound:1}));
      return;
    } catch(error) {
      fallback=(data.language==='en'?'3D unavailable; showing 2D: ':'三维不可用，已切换二维：')+String(error);
      notify('webgl_fallback',{reason:String(error)},data);data={...data,view:'2d'};
    }
  }
  if(fallback)window.replicaWorkbench?.update(data);
  scene3d?.setVisible(false);if(sceneHost)sceneHost.style.display='none';plot.style.display='block';
  compact = isCompact(data);
  const narrow = plot.clientWidth < 900;
  const compactEnergy = data.mode === 'relative'
    ? data.kind === 'gibbs_total' ? 'ΔG' : data.kind === 'gibbs_correction' ? 'ΔGcorr' : 'ΔE'
    : data.mode === 'direct_difference'
      ? data.kind === 'gibbs_total' ? 'ΔG direct' : data.kind === 'gibbs_correction' ? 'ΔGcorr direct' : 'ΔE direct'
    : data.kind === 'gibbs_total' ? 'G' : data.kind === 'gibbs_correction' ? 'Gcorr' : 'E';
  const energyAxis = (narrow ? compactEnergy : data.energy_label) + ' / ' + data.unit_label;
  const style=data.visual_style||{}, fg=style.foreground||(data.dark?'#dce8e2':'#234539'), bg=style.background||(data.dark?'#241E30':'#FCFAFF');
  const grid=style.grid||(data.dark?'#40344E':'#E9E1EF'), zero=style.zero||(data.dark?'#B9ACC9':'#6E627D');
  const {all,labels}=traces(data);
  const visibleCategories=data.paths.filter(p=>p.visible).map(p=>p.category);
  const sceneAxis={gridcolor:grid,zerolinecolor:zero,color:fg,showbackground:true,
    backgroundcolor:translucent(bg,.22),showline:true,linecolor:zero,tickfont:{size:12}};
  // A view-state save can round-trip through Qt while a native camera gesture is still settling.
  // In an existing 3D scene, presets/reset use Plotly.relayout directly. Metadata/selection
  // renders retain the live camera; saved cameras apply on first render or a context/view change.
  const sameCameraContext=shown&&shown.view==='3d'&&data.view==='3d'&&shown.context===data.context;
  const retainLiveCamera=sameCameraContext;
  const liveScene=plot._fullLayout&&plot._fullLayout.scene&&plot._fullLayout.scene._scene;
  const camera=retainLiveCamera&&liveScene?liveScene.getCamera():data.viewport.camera||data.default_camera;
  if(!retainLiveCamera)clearTimeout(cameraFlushTimer);
  annotations=labels;
  const pointFor = a => data.paths.find(p=>p.id===a.path_id).points.find(p=>p.entry_id===a.entry_id);
  const layout={paper_bgcolor:bg,plot_bgcolor:bg,font:{family:'Segoe UI,Microsoft YaHei,Noto Sans CJK SC,sans-serif',color:fg,size:12},
    margin:compact?{l:12,r:12,t:28,b:15}:narrow?{l:106,r:16,t:36,b:52}:{l:76,r:24,t:45,b:60},hovermode:'closest',dragmode:data.camera_dragmode|| (data.view==='3d'?'orbit':'pan'),
    hoverlabel:{bgcolor:style.label_background||bg,bordercolor:style.label_line||zero,font:{color:fg,size:12},align:'left'},
    modebar:{bgcolor:bg,color:zero,activecolor:style.selection||fg},
    title:{text:esc(data.text.reference)+': '+esc((data.paths.find(p=>p.id===data.active_path_id)||{}).reference_origin==='manual'?'手工参考 · ':'')+esc((data.paths.find(p=>p.id===data.active_path_id)||{}).reference||'—'),font:{size:11},x:.02,y:.99},
    uirevision:data.context+'/'+data.view,selectionrevision:data.context,
    showlegend:!bridge&&!compact&&data.paths.length>1,legend:{orientation:'h',y:-.2,font:{size:12},groupclick:'togglegroup'},
    xaxis:{title:{text:esc(data.text.step)},tickvals:data.ticks,ticktext:data.tick_labels,zeroline:false,gridcolor:grid,griddash:'dot',...(data.viewport.x_range?{range:data.viewport.x_range,autorange:false}:{})},
    yaxis:{title:{text:esc(energyAxis)},zeroline:data.mode!=='absolute',zerolinecolor:zero,zerolinewidth:2,
      gridcolor:grid,griddash:'dot',range:data.viewport.y_range||data.default_y_range,autorange:false},
    shapes:data.view==='2d'?data.paths.flatMap(path=>path.points.filter(p=>p.selected&&p.valid&&p.value!=null&&path.visible).map(p=>({
      type:'line',xref:'x',yref:'y',x0:p.x,x1:p.x,y0:(data.viewport.y_range||data.default_y_range)[0],y1:p.value,
      line:{color:style.focus||'#F4A06A',width:1,dash:'dot'},layer:'below'}))):[],
    annotations:labels.map(a=>{const p=pointFor(a);return {x:a.x,y:a.y,ax:a.ax,ay:a.ay,text:`<b>${p.starred_species?.length?'★ ':''}${esc(p.label_short)}</b><br>${esc(p.value_label)}`,
      showarrow:true,arrowhead:0,arrowwidth:.1,arrowcolor:'rgba(0,0,0,0)',font:{color:p.selected?style.focus||'#F4A06A':fg,size:13},bgcolor:'rgba(0,0,0,0)',opacity:1};}),
    scene:{xaxis:{...sceneAxis,title:{text:compact?'':esc(data.text.step),font:{size:11}},tickvals:data.ticks,ticktext:data.tick_labels},
      yaxis:{...sceneAxis,title:{text:compact?'':esc(data.text.category),font:{size:11}},tickvals:visibleCategories,
        ticktext:data.paths.filter(p=>p.visible).map(p=>String(p.label).length>20?String(p.label).slice(0,19)+'…':String(p.label)),
        range:visibleCategories.length?[Math.min(...visibleCategories)-.5,Math.max(...visibleCategories)+.5]:[-.5,.5]},
      zaxis:{...sceneAxis,title:{text:esc(compactEnergy)+' / '+esc(data.unit_label),font:{size:13}},nticks:compact?3:6,zeroline:true,zerolinewidth:2},
      bgcolor:bg,aspectmode:'manual',aspectratio:{x:1.7,y:Math.max(1,Math.min(1.5,data.paths.length*.65)),z:1.25},
      dragmode:data.camera_dragmode||'orbit',camera}}
  if(data.view==='2d')for(const path of data.paths)if(path.visible)for(const point of path.points)if(point.missing_transition_state){
    layout.annotations.push({xref:'x',yref:'paper',x:point.x,y:.88,text:`${esc(point.label_short)}<br><b>NOT FOUND</b>`,
      showarrow:false,font:{color:style.warning||'#B65D57',size:11},bgcolor:style.label_background||bg,
      bordercolor:style.warning||'#B65D57',borderwidth:1,borderpad:4});
  }
  if(data.barrier && data.view==='2d') {
    const path=data.paths.find(p=>p.id===data.barrier.path_id), p=path&&path.points.find(p=>p.entry_id===data.barrier.to_entry);
    if(p && path.visible) {
      const [ax,ay]=data.barrier.label_offset;
      layout.annotations.push({x:p.x,y:p.value,ax,ay,text:esc(data.barrier_label)+' = '+num(data.barrier.value)+' '+esc(data.unit_label),
        showarrow:true,arrowhead:2,arrowwidth:1.2,arrowcolor:style.focus||'#F4A06A',font:{color:fg},bgcolor:style.label_background||bg,
        bordercolor:style.focus||'#F4A06A',borderwidth:1,borderpad:4});
      annotations.push({barrier:true,ax,ay});
    }
  }
  if(data.view==='2d') layout.annotations.push({xref:'paper',yref:'paper',x:1,y:1.08,xanchor:'right',yanchor:'bottom',
    text:esc(data.text.guide),showarrow:false,font:{color:zero,size:10},bgcolor:'rgba(0,0,0,0)'});
  syncing=true;
  await Plotly.react(plot,all,layout,{responsive:true,displaylogo:false,displayModeBar:!data.workbench,scrollZoom:true,typesetMath:false,
    locale:data.language==='en'?'en':'zh-CN',
    editable:false,edits:{annotationPosition:data.view==='2d'},modeBarButtonsToRemove:['toImage','sendDataToCloud','autoScale2d'],
    modeBarButtonsToAdd:data.view==='2d'?['select2d','lasso2d']:[]});
  shown=data;renderCount++;syncing=false;
  // A camera event from the previous envelope can be rejected while Qt publishes a newer revision.
  // Reconcile the retained live camera with this freshly rendered envelope so the gesture is not lost.
  if(retainLiveCamera){
    const current=plot._fullLayout?.scene?._scene?.getCamera();
    if(current&&!sameCamera(current,data.viewport.camera||data.default_camera)){
      shown.viewport={...shown.viewport,camera:current};localViewports['3d']=shown.viewport;
      notify('view_state',{viewport:{camera:current}});
    }
  }
  plot.querySelectorAll('.annotation-arrow').forEach(arrow=>arrow.style.pointerEvents='none');
  document.getElementById('notice').textContent=[fallback,...(bridge&&!data.workbench?[]:data.warnings),
    all.some(t=>t.customdata&&t.customdata.length&&t.visible===true)?'':data.text.empty].filter(Boolean).join(' · ');
  document.body.style.background=bg;
  document.body.style.color=fg;
  for(const [key,value] of Object.entries({background:bg,foreground:fg,border:style.label_line||zero,
      surface:style.label_background||bg,warning:style.warning||zero})) {
    document.documentElement.style.setProperty('--plot-'+key,value);
  }
  if(!bound){ bind(); bound=true; }
  const points=data.paths.flatMap(path=>path.points.filter(p=>p.valid).map(p=>({path_id:path.id,entry_id:p.entry_id,node_id:p.node_id,value:p.value})));
  if(bridge) bridge.rendered(JSON.stringify({project_id:data.project_id,revision:data.revision,render_id:data.render_id,view:data.view,
    points,plotly_version:Plotly.version,trace_count:all.length,svg_count:plot.querySelectorAll('svg.main-svg').length,canvas_count:plot.querySelectorAll('canvas').length,render_count:renderCount,listeners_bound:1}));
}
function bind() {
  // Native camera controls can update the WebGL renderer before Plotly emits a relayout.
  // Flush the settled renderer camera after a pointer/wheel gesture, using the same guarded view event.
  const flushCamera=()=>{
    if(!shown||shown.view!=='3d')return;
    clearTimeout(cameraFlushTimer);
    const context=shown.context;
    const commit=()=>{
      const scene=plot._fullLayout?.scene?._scene;
      if(!scene||!shown||shown.view!=='3d'||shown.context!==context)return;
      if(running||pending||resizePending){cameraFlushTimer=setTimeout(commit,50);return;}
      const camera=scene.getCamera();
      if(sameCamera(camera,shown.viewport.camera||shown.default_camera))return;
      shown.viewport={...shown.viewport,camera};localViewports['3d']=shown.viewport;
      notify('view_state',{viewport:{camera}});
    };
    cameraFlushTimer=setTimeout(commit,180);
  };
  plot.addEventListener('pointerup',flushCamera,true);
  plot.addEventListener('wheel',flushCamera,{capture:true,passive:true});
  plot.on('plotly_click',event=>{
    const point=event.points.find(p=>p.customdata);if(!point)return;
    const c=point.customdata;notify('select',{points:[{path_id:c[0],entry_id:c[1],node_id:c[2]}],additive:!!(event.event&&(event.event.ctrlKey||event.event.shiftKey))});
  });
  plot.on('plotly_hover',event=>{
    const point=event.points.find(p=>p.customdata);
    plot._grprContextPoint=point?point.customdata:null;
  });
  plot.on('plotly_unhover',()=>{plot._grprContextPoint=null;});
  plot.addEventListener('contextmenu',event=>{
    const c=plot._grprContextPoint;
    if(!c)return;
    event.preventDefault();
    notify('species_select',{path_id:c[0],entry_id:c[1],node_id:c[2]});
  },true);
  plot.on('plotly_selected',event=>{
    if(event&&event.points)notify('select',{points:event.points.filter(p=>p.customdata).map(p=>({path_id:p.customdata[0],entry_id:p.customdata[1],node_id:p.customdata[2]})).slice(0,2),additive:false});
  });
  plot.on('plotly_legendclick',event=>{
    const path=shown.paths.find(p=>p.id===plot.data[event.curveNumber].legendgroup);if(!path)return false;
    const hidden=shown.paths.filter(p=>!p.visible).map(p=>p.id), set=new Set(hidden);
    if(path.visible)set.add(path.id);else set.delete(path.id);
    if(bridge) notify('view_state',{hidden_paths:[...set]});
    else {path.visible=!path.visible;enqueue(shown);}
    return false;
  });
  plot.on('plotly_legenddoubleclick',()=>false);
  plot.on('plotly_relayout',change=>{
    if(syncing||!shown)return;
    const viewport={};
    for(const axis of ['x','y']){
      const key=axis+'axis';
      if(change[key+'.range[0]']!==undefined&&change[key+'.range[1]']!==undefined)viewport[axis+'_range']=[change[key+'.range[0]'],change[key+'.range[1]']];
      if(Array.isArray(change[key+'.range']))viewport[axis+'_range']=change[key+'.range'];
      if(change[key+'.autorange'])viewport.reset=true;
    }
    if(change['scene.camera']&&!sameCamera(change['scene.camera'],shown.viewport.camera||shown.default_camera))viewport.camera=change['scene.camera'];
    const offsets={};let barrierOffset;
    annotations.forEach((a,i)=>{
      let ax=change[`annotations[${i}].ax`],ay=change[`annotations[${i}].ay`];
      if(ax===undefined&&ay===undefined)return;
      if(a.barrier)barrierOffset=[ax===undefined?a.ax:ax,ay===undefined?a.ay:ay];
      else offsets[a.entry_id]=[ax===undefined?a.ax:ax,ay===undefined?a.ay:ay];
    });
    if(Object.keys(viewport).length||Object.keys(offsets).length||barrierOffset){
      const {reset,...values}=viewport;
      shown.viewport={...(reset?{}:shown.viewport),...values};
      localViewports[shown.view]=shown.viewport;
      if(bridge)notify('view_state',{viewport,label_offsets:offsets,...(barrierOffset?{barrier_offset:barrierOffset}:{})});
      else {
        for(const path of shown.paths)for(const point of path.points)if(offsets[point.entry_id])point.label_offset=offsets[point.entry_id];
        if(barrierOffset&&shown.barrier)shown.barrier.label_offset=barrierOffset;
      }
    }
  });
  plot.on('plotly_webglcontextlost',()=>{notify('webgl_fallback',{});enqueue({...shown,view:'2d'});});
}
async function enqueue(raw) {
  if(raw!==undefined)pending=typeof raw==='string'?JSON.parse(raw):raw;
  if(running)return;
  running=true;
  try {
    while(pending||resizePending){
      if(pending){const next=pending;pending=null;await render(next);}
      else {
        resizePending=false;
        if(shown?.view==='3d'&&scene3d&&sceneHost.style.display!=='none'){scene3d.resize();continue;}
        if(shown&&plot.clientWidth>0&&plot.clientHeight>0){
          if(isCompact(shown)!==compact)await render(shown);
          await Plotly.Plots.resize(plot);
        }
      }
    }
  }
  catch(error){if(bridge)bridge.failed(String(error));else document.getElementById('notice').textContent=String(error);}
  finally{running=false;}
}
window.grpr={render:enqueue,get shown(){return shown;},get renderCount(){return renderCount;},
 selectPoint:(path_id,entry_id,node_id,additive=false)=>window.GRPR_STANDALONE?window.GRPR_OFFLINE_ACTION({action:'select',path_id,entry_id,node_id,additive}):notify('select',{points:[{path_id,entry_id,node_id}],additive}),
 get renderer3d(){return scene3d;},
 diagnostics:()=>scene3d?.diagnostics(),
 workbenchAction:(values,data)=>{if(window.GRPR_STANDALONE)window.GRPR_OFFLINE_ACTION(values);else if(data||shown)notify('workbench_action',values,data||shown);},
 get queueState(){return {running,pending:!!pending,resizePending,cameraFlushTimer};},
 setCamera:camera=>scene3d&&shown?.view==='3d'?scene3d.setLegacyCamera(camera):Plotly.relayout(plot,{'scene.camera':camera}),
 setViewport:viewport=>{if(scene3d&&shown?.view==='3d'){scene3d.setViewport(viewport);scene3d.commit();}else if(viewport.camera)Plotly.relayout(plot,{'scene.camera':viewport.camera});},
 setDragmode:mode=>{if(scene3d&&shown?.view==='3d')scene3d.mode=mode;else Plotly.relayout(plot,{dragmode:mode});},
 cameraTool:mode=>{
  if(shown?.image_capture)return;
  if(shown?.view==='3d'&&scene3d){
   if(mode==='fit')scene3d.fitBounds();else if(mode==='zoom-in')scene3d.zoom(.8);else if(mode==='zoom-out')scene3d.zoom(1.25);else scene3d.mode=mode;
   if(mode==='zoom-in'||mode==='zoom-out'){scene3d.invalidate();scene3d.commit();}
  }else if(shown?.view==='2d'){
   if(mode==='fit')Plotly.relayout(plot,{'xaxis.autorange':true,'yaxis.autorange':true});
   else if(mode==='zoom')Plotly.relayout(plot,{dragmode:'zoom'});
   else if(mode==='pan')Plotly.relayout(plot,{dragmode:'pan'});
   else if(mode==='zoom-in'||mode==='zoom-out'){
    const factor=mode==='zoom-in'?.8:1.25,changes={};
    for(const axis of ['xaxis','yaxis']){const r=plot._fullLayout?.[axis]?._r;if(!r)continue;const center=(r[0]+r[1])/2,half=(r[1]-r[0])*factor/2;changes[axis+'.range']=[center-half,center+half];}
    if(Object.keys(changes).length)Plotly.relayout(plot,changes);
   }
  }
 },
 pointPosition:(pathId,entryId)=>{
  if(shown?.view==='3d'&&scene3d)return scene3d.pointPosition(pathId,entryId);
  if(!shown||shown.view!=='2d')return null;
  const path=shown.paths.find(p=>p.id===pathId),p=path&&path.points.find(p=>p.entry_id===entryId);
  if(!p||!p.valid)return null;const r=plot.getBoundingClientRect(),f=plot._fullLayout;
  return {x:r.left+f.xaxis._offset+f.xaxis.l2p(p.x),y:r.top+f.yaxis._offset+f.yaxis.l2p(p.value)};
 },reset:()=>scene3d&&shown?.view==='3d'?scene3d.fitBounds():Plotly.relayout(plot,shown.view==='3d'?{'scene.camera':shown.default_camera}:{'xaxis.autorange':true,'yaxis.autorange':true})};
if(window.GRPR_STANDALONE){
 const payload=JSON.parse(document.getElementById('payload').textContent);
 for(const view of ['2d','3d'])localViewports[view]=payload.viewports?.[payload.context+'/'+view]||{};
 window.GRPR_OFFLINE_ACTION=async values=>{
  if(!shown)return;const data=structuredClone(shown);
  if(values.action==='mode'){localViewports[shown.view]=shown.viewport;data.view=values.mode;data.viewport=localViewports[data.view]||{};}
  else if(values.action==='details'){data.details_visible=values.visible;data.details_drawer_open=values.drawer;}
  else if(values.action==='dragmode'){data.camera_dragmode=values.mode;window.grpr.setDragmode(values.mode);}
  else if(values.action==='reset'){window.grpr.reset();return;}
  else if(values.action==='active_path'){
   if(!data.workbench_paths.some(p=>p.id===values.path_id))return;
   data.active_path_id=values.path_id;data.paths=structuredClone(data.offline_paths||data.paths);
   for(const p of data.paths)p.visible=!!data.workbench_paths.find(v=>v.id===p.id)?.visible&&(data.compare||p.id===data.active_path_id);
  }
  else if(values.action==='path'){
   const p=data.workbench_paths.find(p=>p.id===values.path_id);if(p)p.visible=values.visible;
   data.compare=true;data.paths=structuredClone(data.offline_paths||data.paths);
   for(const p of data.paths)p.visible=!!data.workbench_paths.find(v=>v.id===p.id)?.visible;
   data.warnings=data.offline_warnings||data.warnings;
  }else if(values.action==='compare'){
   data.compare=values.enabled;data.paths=structuredClone(data.offline_paths||data.paths);
   for(const p of data.paths)p.visible=!!data.workbench_paths.find(v=>v.id===p.id)?.visible&&(values.enabled||p.id===data.active_path_id);
   if(values.enabled)data.warnings=data.offline_warnings||data.warnings;
  }else if(values.action==='select'){
   for(const p of data.paths)for(const n of p.points)n.selected=p.visible&&((p.id===values.path_id&&n.entry_id===values.entry_id)||(values.additive&&n.selected));
   const vm=data.offline_details?.[values.entry_id];if(vm&&data.inspector){Object.assign(data.inspector,structuredClone(vm));}
  }else return;
  if(values.action==='path'||values.action==='compare'){
   const selected=new Set(shown.paths.flatMap(p=>p.points.filter(n=>n.selected).map(n=>n.entry_id)));
   for(const p of data.paths)for(const n of p.points)n.selected=p.visible&&selected.has(n.entry_id);
  }
  if(data.inspector){
   const table=data.offline_table||payload.inspector,visible=new Set(data.paths.filter(p=>p.visible).map(p=>p.id));
   const indices=table.table_paths.map((p,i)=>visible.has(p.id)?i:-1).filter(i=>i>=0);
   data.inspector.table_paths=indices.map(i=>table.table_paths[i]);
   data.inspector.table_rows=table.table_rows.map(r=>({...r,cells:indices.map(i=>r.cells[i])})).filter(r=>r.cells.some(Boolean));
   for(const row of data.inspector.table_rows)for(const c of row.cells)if(c)c.selected=!!data.paths.find(p=>p.id===c.path_id)?.points.find(n=>n.entry_id===c.entry_id)?.selected;
   const detail=data.inspector.detail;if(detail&&!data.paths.find(p=>p.id===detail.path_id)?.visible){data.inspector.detail=null;data.inspector.structure={status:'no_selection'};}
   data.inspector.pairable=false;
  }
  await enqueue(data);
 };
 enqueue(payload);
 const toggle=document.getElementById('view-toggle'),reset=document.getElementById('reset');
 if(toggle)toggle.onclick=()=>{localViewports[shown.view]=shown.viewport;const view=shown.view==='2d'?'3d':'2d';enqueue({...shown,view,viewport:localViewports[view]||{}});};
 if(reset)reset.onclick=()=>window.grpr.reset();
}else{
 new QWebChannel(qt.webChannelTransport,channel=>{
   bridge=channel.objects.bridge;bridge.dataChanged.connect(enqueue);
   bridge.resetRequested.connect(()=>window.grpr.reset());
   bridge.imageRequested.connect(async request=>{
     try{const q=JSON.parse(request);if(!shown||q.render_id!==shown.render_id)return;
       const snapshot=shown;if(shown.view==='3d'&&!scene3d)throw new Error('Three renderer capture unavailable');
       const uri=shown.view==='3d'?scene3d.capture():await Plotly.toImage(plot,{format:'png',width:1600,height:1000,scale:1});
       if(shown===snapshot)bridge.imageReady(JSON.stringify({request_id:q.request_id,project_id:snapshot.project_id,revision:snapshot.revision,render_id:snapshot.render_id,viewport:snapshot.viewport,uri}));
     }catch(e){bridge.failed(String(e));}
   });
   bridge.pageReady(2,Plotly.version);
 });
}
// Reparenting into the expanded Qt dialog need not emit a browser window resize.
// Serialize plot resizes with react(), coalescing bursts into one animation frame.
new ResizeObserver(()=>{
  if(!shown||resizeFrame)return;
  resizeFrame=requestAnimationFrame(()=>{resizeFrame=0;resizePending=true;enqueue();});
}).observe(host);
window.addEventListener('beforeunload',()=>scene3d?.dispose());
})();
