/* RF2 layout controls use the existing guarded Qt event envelope. RF4 slots stay explicit. */
(() => {
  let current=null;
  const $=id=>document.getElementById(id);
  const icons={compare:'<circle cx="9" cy="12" r="7"/><circle cx="16" cy="12" r="7"/>',reset:'<path d="M19 6a9 9 0 1 0 2 9M19 2v5h-5"/>',export:'<path d="M8 7H4v15h16V7h-4M12 16V2m-4 4 4-4 4 4"/>',orbit:'<circle cx="12" cy="12" r="8"/><path d="m4 11 4 2-1-4m13 4-4-2 1 4"/>',pan:'<path d="M8 12V5a2 2 0 0 1 4 0v6-7a2 2 0 0 1 4 0v8-5a2 2 0 0 1 4 0v9c0 4-3 6-7 6-5 0-6-3-9-8-1-2 1-4 3-2l1 1"/>',zoom:'<circle cx="10" cy="10" r="7"/><path d="m15 15 7 7"/>',fit:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M8 8h8v8H8z"/>'};
  document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true">'+icons[el.dataset.icon]+'</svg>');
  function act(action,extra={}) { if(current)window.grpr.workbenchAction({action,...extra},current); }
  const pathPicker=$('path-picker');
  function closePaths(){pathPicker.hidden=true;$('path-list-control')?.setAttribute('aria-expanded','false');}
  document.addEventListener('click',e=>{if(!pathPicker.contains(e.target)&&!$('path-controls').contains(e.target))closePaths();});
  document.querySelectorAll('[data-mode]').forEach(el=>el.onclick=()=>act('mode',{mode:el.dataset.mode}));
  $('compare-control').onclick=()=>act('compare',{enabled:!current.compare});
  $('reset-control').onclick=()=>act('reset');
  $('export-control').onclick=()=>act('export');
  $('details-menu').onclick=()=>act('menu');
  document.querySelectorAll('[data-drag]').forEach(el=>el.onclick=()=>act('dragmode',{mode:el.dataset.drag}));
  $('zoom-control').onclick=()=>act('dragmode',{mode:'zoom'});
  $('fit-control').onclick=()=>window.grpr.cameraTool('fit');
  const pointList=$('accessible-points'),keyboardStatus=$('keyboard-status');let pointListHasFocus=false,focusedEntry=null;
  pointList.addEventListener('focusin',e=>{pointListHasFocus=true;focusedEntry=e.target?.dataset?.entryId||focusedEntry;});
  pointList.addEventListener('focusout',e=>{if(!pointList.contains(e.relatedTarget))pointListHasFocus=false;});
  function updatePointList(data,t){
    const restoreFocus=pointListHasFocus;
    pointList.replaceChildren();
    const points=(data.paths||[]).filter(p=>p.visible).flatMap(p=>p.points.filter(n=>n.valid&&n.value!=null).map(n=>({p,n})));
    pointList.setAttribute('aria-label',t('Energy profile points','能量剖面节点'));
    for(const {p,n} of points){const b=document.createElement('button');b.type='button';b.setAttribute('role','option');
      b.setAttribute('aria-selected',String(!!n.selected));b.textContent=p.label+' · '+n.label_short+' · '+n.value_label+' '+data.unit_label;
      b.dataset.pathId=p.id;b.dataset.entryId=n.entry_id;b.dataset.nodeId=n.node_id;
      b.onclick=e=>window.grpr.selectPoint(p.id,n.entry_id,n.node_id,!!(e.ctrlKey||e.shiftKey||e.metaKey));pointList.append(b);}
    if(restoreFocus){const selected=points.filter(v=>v.n.selected).at(-1)?.n.entry_id;const target=pointList.querySelector('button[data-entry-id="'+CSS.escape(selected||focusedEntry||'')+'"]')||pointList.querySelector('button');
      if(target)queueMicrotask(()=>{target.focus();focusedEntry=target.dataset.entryId;});}
  }
  pointList.addEventListener('keydown',e=>{
    const buttons=[...pointList.querySelectorAll('button')],index=buttons.indexOf(document.activeElement);let next=index;
    if(e.key==='ArrowRight'||e.key==='ArrowDown')next=Math.min(buttons.length-1,Math.max(0,index)+1);
    else if(e.key==='ArrowLeft'||e.key==='ArrowUp')next=Math.max(0,index<0?0:index-1);
    else if(e.key==='Home')next=0;else if(e.key==='End')next=buttons.length-1;
    else if(e.key==='Escape'){document.activeElement.blur();$('plot').focus?.();return;}
    else if(e.key==='Enter'||e.key===' '){e.preventDefault();document.activeElement.click();return;}
    else return;
    e.preventDefault();buttons[next]?.focus();keyboardStatus.textContent=buttons[next]?.textContent||'';
  });
  window.addEventListener('keydown',e=>{
    if(e.key==='Escape')closePaths();
    if(e.key==='Escape'&&document.body.classList.contains('mobile-details-open')){document.body.classList.remove('mobile-details-open');responsiveDetails();act('details',{visible:!document.body.classList.contains('details-hidden'),drawer:false});}
    if(e.target?.matches?.('input,textarea,select,[contenteditable=true]')||e.ctrlKey||e.altKey||e.metaKey)return;
    if(e.key==='+'||e.key==='=')window.grpr.cameraTool('zoom-in');
    if(e.key==='-'||e.key==='_')window.grpr.cameraTool('zoom-out');
  });
  const showDetails=$('show-details');showDetails.onclick=()=>{
    if(matchMedia('(max-width: 1000px)').matches){const open=!document.body.classList.contains('mobile-details-open');document.body.classList.toggle('mobile-details-open',open);responsiveDetails();}
    else{document.body.classList.toggle('details-hidden');responsiveDetails();}
    act('details',{visible:!document.body.classList.contains('details-hidden'),drawer:document.body.classList.contains('mobile-details-open')});
  };
  function responsiveDetails(){const narrow=matchMedia('(max-width: 1000px)').matches;showDetails.hidden=!narrow&&!document.body.classList.contains('details-hidden');
    if(!narrow)document.body.classList.remove('mobile-details-open');
    const cn=current?.language!=='en';showDetails.textContent=document.body.classList.contains('mobile-details-open')?(cn?'收起详情':'Hide details'):(cn?'详情 / 显示详情':'Details / Show details');
    showDetails.setAttribute('aria-expanded',String(document.body.classList.contains('mobile-details-open')||!document.body.classList.contains('details-hidden')));
  }
  window.addEventListener('resize',responsiveDetails);
  function update(data) {
    current=data;
    const active=!!data.workbench;
    document.body.classList.toggle('workbench',active);
    if(!active)return;
    document.body.classList.toggle('details-hidden',data.details_visible===false);
    document.body.classList.toggle('mobile-details-open',!!data.details_drawer_open&&matchMedia('(max-width: 1000px)').matches);
    const cn=data.language!=='en',t=(en,zh)=>cn?zh:en;
    for(const [key,value] of Object.entries(data.profile_tokens||{}))document.documentElement.style.setProperty('--profile-'+key,value);
    document.documentElement.style.colorScheme=data.dark?'dark':'light';
    document.querySelectorAll('[data-mode]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.mode===data.view)));
    $('compare-label').textContent=t('Compare','比较');
    $('compare-control').setAttribute('aria-pressed',String(data.compare));
    const compareAvailable=(data.workbench_paths||[]).filter(p=>p.visible).length>1;
    $('compare-control').disabled=!compareAvailable;
    $('compare-control').title=compareAvailable?'':t('No compatible paths to compare','没有可比较的兼容路径');
    $('reset-label').textContent=t('Reset camera','重置相机');
    $('export-label').textContent=t('Export','导出');
    if(window.GRPR_STANDALONE){$('export-control').disabled=true;$('export-control').title=t('Export from the desktop app','请从桌面程序导出');}
    $('details-menu').title=t('Editing, theme and camera options','编辑、主题与相机选项');
    const pathControls=$('path-controls');pathControls.replaceChildren();
    const paths=data.workbench_paths||data.paths;
    for(const path of paths.length<=2?paths:[]) {
      const el=document.createElement('button');el.type='button';el.setAttribute('aria-pressed',String(path.visible));el.setAttribute('aria-label',t('Show or hide ','显示或隐藏 ')+path.label);el.title=path.label;
      el.style.setProperty('--path-color',path.color);
      const sw=document.createElement('span');sw.className='switch';sw.setAttribute('aria-hidden','true');
      const name=document.createElement('span');name.className='path-name';name.textContent=path.label;
      el.append(sw,name);el.onclick=()=>act('path',{path_id:path.id,visible:!path.visible});pathControls.append(el);
    }
    const list=document.createElement('button');list.id='path-list-control';list.type='button';
    list.textContent=paths.length>2?t('Paths','路径')+' · '+paths.filter(p=>p.visible).length+'/'+paths.length:'···';
    list.setAttribute('aria-label',t('Path list and colors','路径列表与颜色'));list.title=t('Path list and colors','路径列表与颜色');list.setAttribute('aria-expanded',String(!pathPicker.hidden));
    list.onclick=()=>{pathPicker.hidden=!pathPicker.hidden;list.setAttribute('aria-expanded',String(!pathPicker.hidden));};pathControls.append(list);
    const add=document.createElement('button');add.id='new-path-control';add.type='button';add.textContent='+';add.title=t('Add reaction path','新增反应路径');add.setAttribute('aria-label',add.title);
    add.disabled=!!window.GRPR_STANDALONE||!data.paths_editable;add.onclick=()=>{closePaths();act('new_path');};pathControls.append(add);
    const pickerList=$('path-picker-list');pickerList.replaceChildren();
    for(const path of paths){const row=document.createElement('div');row.className='path-picker-row';row.dataset.pathId=path.id;
      const toggle=document.createElement('button');toggle.type='button';toggle.className='path-visibility';toggle.textContent=path.visible?'✓':'−';toggle.style.color=path.color;toggle.setAttribute('aria-pressed',String(path.visible));toggle.setAttribute('aria-label',t('Show or hide ','显示或隐藏 ')+path.label);toggle.onclick=()=>act('path',{path_id:path.id,visible:!path.visible});
      const name=document.createElement('button');name.type='button';name.className='path-activate';name.textContent=path.label;name.style.color=path.color;name.setAttribute('aria-pressed',String(path.id===data.active_path_id));name.title=t('Set active path','设为活动路径');name.onclick=()=>{closePaths();act('active_path',{path_id:path.id});};
      const color=document.createElement('button');color.type='button';color.className='path-color';color.textContent=path.color;color.style.borderColor=path.color;color.title=t('Change path color','修改路径颜色');color.disabled=!!window.GRPR_STANDALONE||!data.paths_editable;color.onclick=()=>act('path_color',{path_id:path.id});
      row.append(toggle,name,color);pickerList.append(row);
    }
    window.profileInspector?.update(data);
    $('orientation-placeholder').style.visibility=data.view==='3d'?'visible':'hidden';
    $('zoom-control').disabled=$('fit-control').disabled=false;
    document.querySelector('[data-drag="orbit"]').disabled=data.view!=='3d';
    const interaction=data.camera_dragmode||(data.view==='3d'?'orbit':'pan');
    document.querySelectorAll('[data-drag]').forEach(el=>el.setAttribute('aria-pressed',String(interaction!=='zoom'&&el.dataset.drag===interaction)));
    $('zoom-control').setAttribute('aria-pressed',String(interaction==='zoom'));
    $('orbit-label').textContent=t('Orbit','旋转');$('pan-label').textContent=t('Pan','平移');$('zoom-label').textContent=t('Zoom','缩放');$('fit-label').textContent=t('Fit','适应');
    $('operation-hint').textContent=data.view==='3d'?t('Drag to orbit · Scroll to zoom','拖动旋转 · 滚轮缩放'):t('Drag to pan · Scroll or +/- to zoom','拖动平移 · 滚轮或 +/- 缩放');
    updatePointList(data,t);responsiveDetails();
  }
  window.replicaWorkbench={update};
})();
