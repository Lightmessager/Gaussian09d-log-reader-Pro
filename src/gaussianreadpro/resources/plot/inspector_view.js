/* RF4 same-page inspector, SVG overview and explicit-ID energy table. */
(() => {
  const $=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';let current=null,molecule=null,modulePending=null,hidden=false;
  const text=(tag,value,cls)=>{const e=document.createElement(tag);e.textContent=value;if(cls)e.className=cls;return e;};
  const svg=(tag,attrs,parent)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));parent.append(e);return e;};
  const act=(action,extra={})=>window.grpr.workbenchAction({action,...extra},current);
  const select=(cell,event)=>window.grpr.selectPoint(cell.path_id,cell.entry_id,cell.node_id,!!(event.ctrlKey||event.shiftKey||event.metaKey));
  const toggle=()=>{hidden=!document.body.classList.contains('details-hidden');document.body.classList.toggle('details-hidden',hidden);$('show-details').hidden=!hidden;molecule?.setVisible(!hidden);act('details',{visible:!hidden,drawer:false});};
  $('show-details').onclick=toggle;
  function sourceButton(source,index,cn){const b=text('button',source.source_label+' · '+(cn?'作业 ':'Job ')+(source.job_ordinal||'—')+' · '+(cn?'行 ':'line ')+source.line,'source-link');b.title=source.kind+' · SHA-256 '+(source.source_sha256||'—')+' · '+source.state;b.onclick=()=>act('locate_source',{index});return b;}
  function update(data){current=data;if(!data.workbench||!data.inspector)return;hidden=data.details_visible===false;const cn=data.language!=='en',t=(en,zh)=>cn?zh:en,vm=data.inspector,d=vm.detail;
    $('selected-title').textContent=t('Selected','已选中')+' · '+(d?d.path_label+' / '+d.label:'—');
    const uniqueSources=[];for(const [i,s] of (d?.sources||[]).entries())if(!uniqueSources.some(v=>v.source.source_file_id===s.source_file_id&&v.source.job_id===s.job_id))uniqueSources.push({source:s,index:i});
    const menu=$('inspector-menu'),pairButton=$('pair-steps');menu.replaceChildren();
    for(const [label,action,disabled] of [[t('Edit expression','编辑表达式'),'edit_expression',!d||!vm.editable],[t('Locate source','定位来源'),'locate_source',!d?.sources.length],[t('Copy value','复制数值'),'copy_value',!d?.valid],[t('Hide details','隐藏详情'),'hide',false],[t('More workbench options','更多工作台选项'),'menu',false]]){const b=text('button',label);b.dataset.action=action;b.disabled=disabled;b.onclick=()=>{menu.hidden=true;if(action==='hide')toggle();else if(action==='locate_source'&&uniqueSources.length>1){$('source-list').hidden=false;$('source-list').scrollIntoView({block:'nearest'});}else act(action);};menu.append(b);}
    menu.append(pairButton);pairButton.hidden=false;
    $('details-menu').onclick=()=>{menu.hidden=!menu.hidden;};$('details-menu').title=t('Selected node actions','所选节点操作');
    const dl=$('details-fields');dl.replaceChildren();const energyLabel=data.mode==='absolute'?t('Energy','能量'):data.mode==='direct_difference'?t('Direct difference','直接差值'):t('Relative energy','相对能量');
    const barrierName=d?.barrier?t('Activation barrier (from ','活化势垒（相对 ')+d.barrier.first+(cn?'）':')'):t('Activation barrier','活化势垒');
    const fields=[[t('Structure','结构'),d?.label||'—'],[t('Path','路径'),d?.path_label||'—'],[energyLabel,d?.valid?d.value_label+' '+data.unit_label:'—','energy'],[barrierName,d?.barrier?d.barrier_label+' '+data.unit_label:d?.role==='transition_state'?t('Predecessor not set','未设置前驱'):'—','energy'],[t('Absolute energy','绝对能量'),d?.absolute_hartree!=null?d.absolute_hartree.toFixed(6)+' Eh':'—'],[t('Source file','来源文件'),null],[t('Job','作业'),uniqueSources.length===1?String(uniqueSources[0].source.job_ordinal||'—'):uniqueSources.length?t('Multiple','多个'):'—']];
    for(const [name,value,cls] of fields){const dt=text('dt',name),dd=text('dd',value||'');if(cls)dd.className=cls;
      if(value===null){if(uniqueSources.length===1)dd.append(sourceButton(uniqueSources[0].source,uniqueSources[0].index,cn));else if(uniqueSources.length){const button=text('button',t('Multiple sources','多个来源')+' ('+uniqueSources.length+')','source-link');button.onclick=()=>{$('source-list').hidden=!$('source-list').hidden;};dd.append(button);}else dd.textContent='—';}
      dt.title=name;dd.title=dd.textContent;dl.append(dt,dd);}
    const sources=$('source-list');sources.replaceChildren();(d?.sources||[]).forEach((s,i)=>{const row=document.createElement('div');row.append(sourceButton(s,i,cn),text('small',(s.role==='reference'?t('Reference','参考'):t('Value','体系'))+' · '+s.kind+' · SHA-256 '+(s.source_sha256||'—')));sources.append(row);});
    if(!d?.sources.length)sources.hidden=true;
    const candidates=vm.structure_candidates,selector=$('structure-source');selector.replaceChildren();selector.setAttribute('aria-label',t('Molecule source job','分子来源作业'));
    if(candidates.length>1){const option=text('option',t('Choose a source molecule…','选择来源分子…'));option.value='';selector.append(option);}
    candidates.forEach((c,i)=>{const option=text('option',c.source_label+' · Job '+c.job_ordinal);option.value=String(i);option.selected=vm.structure_choice?.[0]===c.source_file_id&&vm.structure_choice?.[1]===c.job_id;selector.append(option);});
    selector.hidden=candidates.length<2;selector.onchange=()=>{if(selector.value!=='')act('structure_source',{index:Number(selector.value)});};
    const model=vm.structure||{},status=model.status;const messages={loading:t('Reading verified job…','正在读取已验证作业…'),choose_source:t('Choose one source molecule for this expression','请选择此表达式的一个来源分子'),no_selection:t('No valid selected structure','没有有效的选中结构'),no_structure:t('No structure in this job','此作业没有可用结构'),invalid_orientation:t('No complete supported orientation in this job','此作业没有完整的可用坐标段'),unsupported_units:t('Unsupported coordinate units','不支持此坐标单位'),changed:t('Source changed; preview withheld','来源已变化，未显示结构'),size_limit:t('Preview file limit: 64 MiB','预览文件上限：64 MiB'),atom_limit:t('Preview atom limit: 1000','预览原子数上限：1000')};
    messages.no_source=t('No source molecule in this expression','此表达式没有来源分子');
    messages.not_exported=t('No coordinates embedded for this node','此节点未嵌入坐标');
    $('structure-status').textContent=status==='available'?(model.synthetic?t('Synthetic example · ','合成示例 · '):'')+model.orientation+' · Å · '+model.atoms.length+t(' atoms',' 个原子'):messages[status]||t('Source unavailable: ','来源不可用：')+status;
    $('structure-status').classList.toggle('available',status==='available');
    $('structure-provenance').textContent=status==='available'?t('Bonds inferred for display','连接键仅为显示推断')+' · '+(cn?'坐标行 ':'coordinate lines ')+model.line_start+'–'+model.line_end:'';
    $('structure-provenance').title=status==='available'?'SHA-256 '+model.source_sha256+' · '+model.job_id+' · '+model.parser_version:'';
    const present=()=>{if(!molecule||!current?.inspector)return;molecule.setData(current.inspector.structure,current.dark);molecule.setVisible(!hidden);};
    if(!molecule&&status==='available'&&!modulePending){modulePending=(window.GRPR_MODULES?.molecule||import('./molecule_view.js')).then(({MoleculeView})=>{molecule=new MoleculeView($('molecule-stage'));present();}).catch(e=>{$('structure-status').textContent=t('3D preview unavailable: ','结构预览不可用：')+String(e);}).finally(()=>{modulePending=null;});}else present();
    $('overview-title').textContent=data.paths.length>2?t('Multi-path energy profile (2D view)','多路径能量剖面（二维）'):t('Two-path energy profile (2D view)','双路径能量剖面（二维）');renderOverview(data);
    $('table-title').textContent=t('Key energies','关键能量')+' ('+data.unit_label+')';renderTable(data);
    $('pair-steps').textContent=t('Pair selected steps','配对所选步骤');$('pair-steps').disabled=!vm.pairable;$('pair-steps').title=t('Ctrl/Shift-select one node on each path, then pair their IDs','Ctrl/Shift 在两条路径各选一个节点，再配对其 ID');$('pair-steps').onclick=()=>act('pair_steps');
    if(window.GRPR_STANDALONE){
      for(const b of document.querySelectorAll('.source-link,[data-action="edit_expression"],[data-action="locate_source"],[data-action="menu"],#pair-steps,#structure-source')){b.disabled=true;b.title=t('Requires the desktop project and source logs','需要桌面项目及来源日志');}
      const copy=menu.querySelector('[data-action="copy_value"]');if(copy)copy.onclick=()=>{const value=d?.value_label+' '+data.unit_label;const input=document.createElement('textarea');input.value=value;document.body.append(input);input.select();document.execCommand('copy');input.remove();menu.hidden=true;};
    }
  }
  function renderOverview(data){const root=$('overview-chart');root.replaceChildren();root.setAttribute('viewBox','0 0 350 190');const paths=data.paths.filter(p=>p.visible),values=paths.flatMap(p=>p.points.filter(n=>n.valid&&n.value!=null).map(n=>n.value));
    let legend=$('overview-legend');if(!legend){legend=document.createElement('div');legend.id='overview-legend';root.before(legend);}legend.replaceChildren();legend.hidden=paths.length<=2;
    if(paths.length>2)for(const path of paths){const item=text('span',path.label);item.style.color=path.color;item.title=path.label;legend.append(item);}
    if(!values.length){svg('text',{x:175,y:90,'text-anchor':'middle',fill:'currentColor'},root).textContent=data.text.empty;return;}
    const levels=data.mode==='absolute'?values:[...values,0];const lo=Math.min(...levels),hi=Math.max(...levels),span=Math.max(hi-lo,.001),min=lo-span*.12,max=hi+span*.18;
    const steps=paths.flatMap(p=>p.points.map(n=>n.x)),xmin=Math.min(...steps),xmax=Math.max(...steps),sx=x=>42+(x-xmin)/Math.max(xmax-xmin,1)*292,sy=y=>155-(y-min)/(max-min)*119;
    for(let i=0;i<5;i++){const v=lo+(hi-lo)*i/4,y=sy(v);svg('line',{x1:42,x2:334,y1:y,y2:y,stroke:'currentColor',opacity:.13},root);svg('text',{x:35,y:y+4,'text-anchor':'end',fill:'currentColor','font-size':10},root).textContent=Number(v.toPrecision(3));}
    svg('line',{x1:42,x2:334,y1:sy(0),y2:sy(0),stroke:'currentColor',opacity:.5},root);
    if(paths.length<=2)paths.forEach((p,i)=>{svg('circle',{cx:83+i*75,cy:12,r:4,fill:p.color},root);svg('text',{x:91+i*75,y:16,fill:'currentColor','font-size':11},root).textContent=p.label;});
    for(const path of paths){for(const run of path.curve_runs)svg('polyline',{points:run.map(p=>sx(p[0])+','+sy(p[1])).join(' '),fill:'none',stroke:path.color,'stroke-width':2},root);
      for(const n of path.points){if(!n.valid||n.value==null)continue;const x=sx(n.x),y=sy(n.value);if(n.selected){svg('line',{x1:x,x2:x,y1:y,y2:155,stroke:'var(--profile-focus)','stroke-dasharray':'3 3',opacity:.6},root);svg('circle',{cx:x,cy:y,r:7,fill:'none',stroke:'var(--profile-focus)','stroke-width':2},root);}
        const c=svg('circle',{cx:x,cy:y,r:4.5,fill:'var(--profile-canvas)',stroke:path.color,'stroke-width':2,tabindex:0,role:'button','aria-label':path.label+' / '+n.label_short+' / '+n.value_label},root);c.dataset.pathId=path.id;c.dataset.entryId=n.entry_id;const cell={path_id:path.id,entry_id:n.entry_id,node_id:n.node_id};
        c.onclick=e=>{const overlaps=paths.flatMap(p=>p.points.filter(v=>v.valid&&v.value!=null&&Math.abs(sx(v.x)-x)<1&&Math.abs(sy(v.value)-y)<1).map(v=>({path_id:p.id,entry_id:v.entry_id,node_id:v.node_id})));const detail=current.inspector.detail,index=overlaps.findIndex(v=>v.path_id===detail?.path_id&&v.entry_id===detail?.entry_id);select(overlaps[(index+1)%overlaps.length]||cell,e);};
        c.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(cell,e);}};svg('title',{},c).textContent=path.label+' · '+n.label_short+' · '+n.value_label+' '+data.unit_label+' · '+(data.language==='en'?'Overlapping nodes: click to cycle':'重叠节点：重复点击切换');}}
    for(const x of [...new Set(steps)]){svg('text',{x:sx(x),y:169,'text-anchor':'middle',fill:'currentColor','font-size':10},root).textContent=x+1;}
    svg('text',{x:188,y:187,'text-anchor':'middle',fill:'currentColor','font-size':11},root).textContent=data.language==='en'?'Reaction coordinate (step)':'反应坐标（步骤）';
    const symbol=(data.mode==='absolute'?'':'Δ')+(data.kind==='gibbs_total'?'G':data.kind==='gibbs_correction'?'Gcorr':'E');svg('text',{transform:'translate(12,100) rotate(-90)','text-anchor':'middle',fill:'currentColor','font-size':11},root).textContent=symbol+' / '+data.unit_label;
  }
  function renderTable(data){const vm=data.inspector,table=$('key-energy-table');table.style.minWidth=vm.table_paths.length>2?((vm.table_paths.length+1)*90)+'px':'';table.replaceChildren();const head=document.createElement('thead'),tr=document.createElement('tr');tr.append(text('th',data.language==='en'?'Structure':'结构'));for(const p of vm.table_paths){const th=text('th',p.label);th.style.color=p.color;tr.append(th);}head.append(tr);table.append(head);const body=document.createElement('tbody');
    for(const row of vm.table_rows){const tr=document.createElement('tr');tr.append(text('th',row.label));for(const [i,c] of row.cells.entries()){const td=document.createElement('td');if(c){const b=text('button',c.valid?c.value_label:'—',c.selected?'selected':'');b.disabled=!c.valid;b.dataset.pathId=c.path_id;b.dataset.entryId=c.entry_id;b.title=vm.table_paths[i].label+' / '+c.label+' · '+c.entry_id;b.onclick=e=>select(c,e);td.append(b);}else td.textContent='—';tr.append(td);}body.append(tr);}table.append(body);
  }
  window.profileInspector={update,get molecule(){return molecule;}};
  window.addEventListener('beforeunload',()=>molecule?.dispose());
})();
