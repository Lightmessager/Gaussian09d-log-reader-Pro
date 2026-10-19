/* Three.js r170, offline. Display geometry only: scientific samples/values come from Python.
 * ProfileRenderer boundary: mount/setData/setSelection/setViewport/resize/capture/dispose.
 * World coordinates: X step, Y discrete path category, Z common energy transform.
 */
import * as T from './vendor/three.module.min.js';

const V=(x=0,y=0,z=0)=>new T.Vector3(x,y,z);
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const color=c=>new T.Color(c);
const disposeTree=root=>root.traverse(o=>{o.geometry?.dispose();for(const m of (Array.isArray(o.material)?o.material:[o.material]))if(m){m.map?.dispose();m.dispose();}});

// Explicit legacy conversion, rather than reinterpreting Plotly eye as world units.
// Plotly's aspect-normalized eye/center are transformed by the common scene extents.
export function legacyViewport(camera, extent) {
  const read=(key,fallback)=>['x','y','z'].map((a,i)=>finite(camera?.[key]?.[a])?camera[key][a]:fallback[i]);
  const eye=read('eye',[-1.1,-1.9,1.05]),center=read('center',[0,0,0]),up=read('up',[0,0,1]);
  const target=center.map((v,i)=>v*extent[i]/2);
  const position=eye.map((v,i)=>v*extent[i]/2+target[i]);
  if(Math.hypot(...position.map((v,i)=>v-target[i]))<.01||Math.hypot(...up)<.01)return null;
  return {version:1,projection:'orthographic',position,target,up,zoom:1,migrated_from:'plotly-v1'};
}

export class ProfileRenderer {
  constructor(callbacks={}) {this.callbacks=callbacks;this.listeners=[];this.frame=0;this.frames=0;this.visible=true;this.context=null;this.nodes=[];this.pickObjects=[];this.width=1;this.height=1;this.mode='orbit';this.hover=null;}
  mount(host,cubeHost) {
    this.host=host;this.cubeHost=cubeHost;
    this.renderer=new T.WebGLRenderer({antialias:true,alpha:true,preserveDrawingBuffer:true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2.5));
    this.renderer.outputColorSpace=T.SRGBColorSpace;this.renderer.setClearColor(0,0);
    this.canvas=this.renderer.domElement;this.canvas.className='profile-three-canvas';host.append(this.canvas);
    this.overlay=document.createElement('div');this.overlay.className='scene-overlay';host.append(this.overlay);
    this.tooltip=document.createElement('div');this.tooltip.className='scene-tooltip';this.tooltip.setAttribute('role','status');this.overlay.append(this.tooltip);
    this.scene=new T.Scene();this.group=new T.Group();this.scene.add(this.group);
    this.camera=new T.OrthographicCamera(-6,6,5,-5,.01,500);this.camera.up.set(0,0,1);this.target=V();
    this.camera.position.set(6,-12,8);this.camera.lookAt(this.target);
    this.raycaster=new T.Raycaster();this.pointer=new T.Vector2();
    const on=(el,type,fn,options)=>{el.addEventListener(type,fn,options);this.listeners.push(()=>el.removeEventListener(type,fn,options));};
    on(this.canvas,'pointerdown',e=>{if(e.button>1)return;this.drag={x:e.clientX,y:e.clientY,lastX:e.clientX,lastY:e.clientY,button:e.button,moved:false};this.canvas.setPointerCapture(e.pointerId);});
    on(this.canvas,'pointermove',e=>{
      const d=this.drag;
      if(d){const dx=e.clientX-d.lastX,dy=e.clientY-d.lastY;d.lastX=e.clientX;d.lastY=e.clientY;
        if(Math.hypot(e.clientX-d.x,e.clientY-d.y)>5)d.moved=true;
        if(d.moved){this.hover=null;if(this.mode==='pan'||e.shiftKey||d.button===1)this.pan(dx,dy);else if(this.mode==='zoom')this.zoom(Math.exp(dy*.008));else this.orbit(dx,dy);this.invalidate();}
      }else{const hit=this.pick(e.clientX,e.clientY);if(hit!==this.hover){this.hover=hit;this.invalidate();}this.canvas.style.cursor=hit?'pointer':this.mode==='pan'?'grab':'default';}
    });
    on(this.canvas,'pointerup',e=>{const d=this.drag;this.drag=null;if(!d)return;
      if(d.moved)this.commit();else{const hit=this.pick(e.clientX,e.clientY);if(hit)this.callbacks.select?.(hit.path,hit.point,!!(e.ctrlKey||e.shiftKey||e.metaKey));}
    });
    on(this.canvas,'contextmenu',e=>{const hit=this.pick(e.clientX,e.clientY);if(!hit)return;
      e.preventDefault();this.callbacks.context?.(hit.path,hit.point);
    });
    on(this.canvas,'pointercancel',()=>{this.drag=null;this.commit();});
    on(this.canvas,'pointerleave',()=>{if(!this.drag){this.hover=null;this.invalidate();}});
    on(this.canvas,'wheel',e=>{e.preventDefault();this.zoom(Math.exp(e.deltaY*.001));this.invalidate();clearTimeout(this.wheelTimer);this.wheelTimer=setTimeout(()=>this.commit(),160);},{passive:false});
    on(document,'keydown',e=>{if(e.key==='Escape'){this.hover=null;this.invalidate();}});
    on(document,'visibilitychange',()=>{if(document.hidden)this.cancelFrame();else this.invalidate();});
    on(this.canvas,'webglcontextlost',e=>{e.preventDefault();this.callbacks.failed?.('WebGL context lost');});
    this.mountCube(on);this.resize();return this;
  }
  setVisible(visible){this.visible=visible;this.canvas.style.display=visible?'':'none';this.overlay.style.display=visible?'':'none';if(this.cubeHost)this.cubeHost.style.visibility=visible?'visible':'hidden';if(visible)this.invalidate();else this.cancelFrame();}
  setData(data) {
    const previousDepth=this.depth;
    const cameraContext=[data.project_id,data.unit,data.kind,data.mode].join('/');
    const newContext=this.context!==cameraContext;this.context=cameraContext;this.data=data;this.mode=data.camera_dragmode||'orbit';this.hover=null;
    disposeTree(this.group);this.group.clear();this.pickObjects=[];this.nodes=[];
    this.overlay.querySelectorAll('.scene-label,.scene-axis-label,.scene-missing-banner').forEach(e=>e.remove());this.axisLabels=[];this.missingLabels=[];
    const paths=data.paths.filter(p=>p.visible),points=paths.flatMap(p=>p.points.filter(n=>n.valid&&finite(n.value)));
    const xs=points.map(p=>p.x),zs=points.map(p=>p.value);
    this.xmin=xs.length?Math.min(...xs):0;this.xmax=xs.length?Math.max(...xs):1;if(this.xmin===this.xmax)this.xmax=this.xmin+1;
    let lo=zs.length?Math.min(...zs):-1,hi=zs.length?Math.max(...zs):1;
    const span=Math.max(hi-lo,data.unit==='hartree'?.002:.5);
    if(data.mode!=='absolute'){lo=Math.min(lo,0);hi=Math.max(hi,0);}
    // Nice common ticks, no path-specific offset or scaling.
    const rough=(Math.max(hi-lo,span)*1.16)/4, power=10**Math.floor(Math.log10(rough));
    const step=[1,2,5,10].map(v=>v*power).find(v=>v>=rough)||power*10;
    this.zmin=Math.floor((lo-span*.06)/step)*step;this.zmax=Math.ceil((hi+span*.06)/step)*step;
    this.depth=Math.max(1.8,(data.paths.length-1)*1.8+1.1);this.extent=[12.4,this.depth,4.7];
    this.world=(x,category,z)=>V((x-this.xmin)/(this.xmax-this.xmin)*11.9-5.95,category*1.8-(data.paths.length-1)*.9,(z-this.zmin)/(this.zmax-this.zmin)*4.7-2.35);
    this.bounds=new T.Box3(V(-6.2,-this.depth/2,-2.35),V(6.2,this.depth/2,2.35));
    const fg=data.visual_style?.foreground||'#dfd6f4',grid=data.dark?'#a99dc6':'#6c5b89';
    const z0=this.world(0,0,this.zmin).z;
    const plane=(z,opacity)=>{const mesh=new T.Mesh(new T.PlaneGeometry(12.4,this.depth),new T.MeshBasicMaterial({color:data.dark?'#b69add':'#9670be',transparent:true,opacity,side:T.DoubleSide,depthWrite:false}));mesh.position.z=z;mesh.renderOrder=0;this.group.add(mesh);};
    plane(z0,.055);if(this.zmin<=0&&this.zmax>=0)plane(this.world(0,0,0).z,.08);
    const line=(a,b,c=grid,opacity=.14,dashed=false,width=1)=>{
      if(dashed)this.strip([a,b],c,width,opacity,2,true);
      else this.strip([a,b],c,width,opacity,1);
    };
    for(let i=0;i<=12;i++){const x=-6.2+i*12.4/12;line(V(x,-this.depth/2,z0),V(x,this.depth/2,z0));}
    for(let i=0;i<=6;i++){const y=-this.depth/2+i*this.depth/6;line(V(-6.2,y,z0),V(6.2,y,z0));}
    for(let z=this.zmin;z<=this.zmax+step*.01;z+=step){const w=this.world(0,0,z).z;line(V(-6.2,-this.depth/2,w),V(-6.2,this.depth/2,w));line(V(-6.2,this.depth/2,w),V(6.2,this.depth/2,w));
      this.axisLabel(Number(z.toPrecision(6)).toString(),V(-6.3,-this.depth/2,w),'tick');}
    line(V(-6.2,-this.depth/2,z0),V(6.2,-this.depth/2,z0),fg,.6);
    line(V(-6.2,-this.depth/2,z0),V(-6.2,-this.depth/2,2.35),fg,.6);
    line(V(6.2,-this.depth/2,z0),V(6.2,this.depth/2,z0),fg,.6);
    for(const x of data.ticks)this.axisLabel(String(x+1),this.world(x,0,this.zmin).setY(-this.depth/2-.1),'step');
    this.axisLabel(data.language==='en'?'Reaction coordinate (step)':'反应坐标（步骤）',V(0,-this.depth/2-.48,z0),'x-title');
    const baseSymbol=data.kind==='gibbs_total'?'G':data.kind==='gibbs_correction'?'Gcorr':'E';
    const symbol=(data.mode==='absolute'?'':'Δ')+baseSymbol+(data.mode==='direct_difference'?' direct':'');
    this.energySymbol=symbol;this.axisLabel(symbol+' / '+data.unit_label,V(-6.65,-this.depth/2,0),'z-title');
    for(const path of paths){
      this.axisLabel(path.label,this.world(this.xmax,path.category,this.zmin).add(V(.55,0,0)),'path',path.color);
      for(const run of path.curve_runs){const samples=run.map(p=>this.world(p[0],path.category,p[1]));if(samples.length<2)continue;
        this.curtain(samples,path.color,z0);
        this.strip(samples,path.color,18,.075,4);this.strip(samples,path.color,11,.15,5);this.strip(samples,path.color,7,.22,6);
        this.strip(samples,color(path.color).lerp(color('#ffffff'),.55),2.5,1,7);
      }
      for(const point of path.points){if(!point.valid||!finite(point.value))continue;
        const position=this.world(point.x,path.category,point.value);
        line(position,V(position.x,position.y,z0),point.selected?'#ffab6c':path.color,point.selected?.85:.42,true,point.selected?1.8:1);
        const sprite=this.sprite(path.color,false);sprite.position.copy(position);sprite.userData={path_id:path.id,entry_id:point.entry_id,node_id:point.node_id};sprite.renderOrder=10;this.group.add(sprite);this.pickObjects.push(sprite);
        let ring=null;if(point.selected){ring=this.sprite('#ffa469',true);ring.position.copy(position);ring.renderOrder=11;this.group.add(ring);}
        const label=document.createElement('div');label.className='scene-label'+(point.selected?' selected':'');label.style.color=point.selected?'#ffac73':color(path.color).lerp(color(fg),.5).getStyle();
        const name=document.createElement('strong'),value=document.createElement('span');name.textContent=(point.starred_species?.length?'★ ':'')+point.label_short;value.textContent=point.value_label;label.append(name,value);this.overlay.append(label);
        this.nodes.push({path,point,position,sprite,ring,label});
      }
    }
    for(const path of paths){for(const point of path.points){if(!point.missing_transition_state)continue;
      const card=document.createElement('div');card.className='scene-missing-banner';card.style.setProperty('--missing-color',path.color);
      card.style.setProperty('--missing-index',this.missingLabels.length);
      card.textContent=(data.language==='en'?'NOT FOUND · ':'未找到过渡态 · ')+path.label+' · '+point.label_short+' · '+(data.language==='en'?'no energy value':'无能量值');
      this.overlay.append(card);this.missingLabels.push(card);
    }}
    if(newContext){this.fitBounds(false);this.setViewport(data.viewport);}
    else if(previousDepth!==this.depth){const camera=this.viewport();this.fitBounds(false);this.setViewport({three_v1:camera});}
    this.resize();this.invalidate();
  }
  setSelection(keys){if(!this.data)return;this.setData({...this.data,paths:this.data.paths.map(p=>({...p,points:p.points.map(n=>({...n,selected:keys.some(k=>k[0]===p.id&&k[1]===n.entry_id)}))}))});}
  curtain(samples,c,zmin){
    const pos=[],alpha=[];for(let i=0;i<samples.length-1;i++){const a=samples[i],b=samples[i+1];for(const [p,t] of [[a,1],[V(a.x,a.y,zmin),0],[b,1],[b,1],[V(a.x,a.y,zmin),0],[V(b.x,b.y,zmin),0]]){pos.push(...p);alpha.push(t);}}
    const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(pos,3));g.setAttribute('fade',new T.Float32BufferAttribute(alpha,1));
    const m=new T.ShaderMaterial({uniforms:{tint:{value:color(c)}},vertexShader:'attribute float fade; varying float a; void main(){a=fade;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',fragmentShader:'uniform vec3 tint; varying float a; void main(){gl_FragColor=vec4(tint,.14*a*a);}',transparent:true,depthWrite:false,side:T.DoubleSide});
    // Put each curtain's object origin at its own center for camera-depth sorting.
    g.computeBoundingSphere();const center=g.boundingSphere.center.clone();g.translate(-center.x,-center.y,-center.z);
    const mesh=new T.Mesh(g,m);mesh.position.copy(center);mesh.renderOrder=3;mesh.userData.decoration='curtain';this.group.add(mesh);
  }
  strip(points,c,width,opacity,order,dashed=false){
    if(points.length<2)return;const positions=[],prev=[],next=[],sides=[],indices=[],distances=[];let distance=0;
    points.forEach((p,i)=>{if(i)distance+=p.distanceTo(points[i-1]);for(const s of [-1,1]){positions.push(...p);prev.push(...points[Math.max(i-1,0)]);next.push(...points[Math.min(i+1,points.length-1)]);sides.push(s);distances.push(distance);}if(i<points.length-1){const j=i*2;indices.push(j,j+1,j+2,j+2,j+1,j+3);}});
    const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(positions,3));g.setAttribute('previous',new T.Float32BufferAttribute(prev,3));g.setAttribute('next',new T.Float32BufferAttribute(next,3));g.setAttribute('side',new T.Float32BufferAttribute(sides,1));g.setAttribute('distance',new T.Float32BufferAttribute(distances,1));g.setIndex(indices);
    const m=new T.ShaderMaterial({uniforms:{resolution:{value:new T.Vector2(this.width,this.height)},lineWidth:{value:width},tint:{value:color(c)},alpha:{value:opacity},dashed:{value:dashed}},
      vertexShader:'attribute vec3 previous; attribute vec3 next; attribute float side; attribute float distance; uniform vec2 resolution; uniform float lineWidth; varying float edge; varying float arc; void main(){vec4 p=projectionMatrix*modelViewMatrix*vec4(position,1.);vec4 a=projectionMatrix*modelViewMatrix*vec4(previous,1.);vec4 b=projectionMatrix*modelViewMatrix*vec4(next,1.);vec2 d=(b.xy/b.w-a.xy/a.w)*resolution;d=length(d)>.0001?normalize(d):vec2(1.,0.);p.xy+=vec2(-d.y,d.x)*side*lineWidth/resolution*p.w;gl_Position=p;edge=side;arc=distance;}',
      fragmentShader:'uniform vec3 tint; uniform float alpha; uniform bool dashed; varying float edge; varying float arc; void main(){if(dashed&&mod(arc,.125)>.07)discard;gl_FragColor=vec4(tint,alpha*(1.-smoothstep(.55,1.,abs(edge))));\n#include <colorspace_fragment>\n}',transparent:true,depthWrite:false,side:T.DoubleSide});
    const mesh=new T.Mesh(g,m);mesh.frustumCulled=false;mesh.renderOrder=order;this.group.add(mesh);
  }
  sprite(c,ring){const canvas=document.createElement('canvas');canvas.width=canvas.height=128;const ctx=canvas.getContext('2d');
    if(ring){const glow=ctx.createRadialGradient(64,64,32,64,64,64);glow.addColorStop(0,'#ffa35d66');glow.addColorStop(1,'#ffa35d00');ctx.fillStyle=glow;ctx.fillRect(0,0,128,128);ctx.strokeStyle='#ffab72';ctx.lineWidth=6;ctx.beginPath();ctx.arc(64,64,42,0,Math.PI*2);ctx.stroke();ctx.strokeStyle='#fff5e7';ctx.lineWidth=2;ctx.beginPath();ctx.arc(64,64,36,0,Math.PI*2);ctx.stroke();}
    else{const grad=ctx.createRadialGradient(43,36,2,64,64,62);grad.addColorStop(0,'#fffaff');grad.addColorStop(.32,color(c).lerp(color('#ffffff'),.4).getStyle());grad.addColorStop(1,c);ctx.fillStyle=grad;ctx.beginPath();ctx.arc(64,64,60,0,Math.PI*2);ctx.fill();}
    const texture=new T.CanvasTexture(canvas);texture.colorSpace=T.SRGBColorSpace;return new T.Sprite(new T.SpriteMaterial({map:texture,transparent:true,depthWrite:false,depthTest:false}));
  }
  axisLabel(text,position,kind,c){const el=document.createElement('div');el.className='scene-axis-label '+kind;el.textContent=text;if(c)el.style.color=c;this.overlay.append(el);this.axisLabels.push({el,position});}
  viewport(){return {version:1,projection:'orthographic',position:this.camera.position.toArray(),target:this.target.toArray(),up:this.camera.up.toArray(),zoom:this.camera.zoom};}
  setViewport(viewport={}){let v=viewport.three_v1;if(!v&&viewport.camera)v=legacyViewport(viewport.camera,this.extent);if(!v)return;
    const vector=a=>Array.isArray(a)&&a.length===3&&a.every(x=>finite(x)&&Math.abs(x)<=1000);
    if(v.version!==1||v.projection!=='orthographic'||!vector(v.position)||!vector(v.target)||!vector(v.up)||!finite(v.zoom)||v.zoom<.15||v.zoom>12)return;
    const p=V(...v.position),t=V(...v.target),u=V(...v.up);if(p.distanceTo(t)<.01||u.length()<.01||p.clone().sub(t).normalize().cross(u.clone().normalize()).length()<.001)return;
    this.camera.position.copy(p);this.target.copy(t);this.camera.up.copy(u.normalize());this.camera.zoom=v.zoom;this.camera.lookAt(t);this.camera.updateProjectionMatrix();this.migration=v.migrated_from||null;this.invalidate();
  }
  setLegacyCamera(camera){this.setViewport({camera});this.commit();}
  fitBounds(commit=true){if(!this.bounds)return;this.camera.up.set(0,0,1);this.target.copy(this.bounds.getCenter(V()));this.camera.position.copy(this.target).add(V(6,-12,8));this.camera.zoom=1;this.camera.lookAt(this.target);this.camera.updateMatrixWorld(true);
    const inverse=this.camera.matrixWorldInverse,box=new T.Box3();for(const x of [this.bounds.min.x,this.bounds.max.x])for(const y of [this.bounds.min.y,this.bounds.max.y])for(const z of [this.bounds.min.z,this.bounds.max.z])box.expandByPoint(V(x,y,z).applyMatrix4(inverse));
    this.fitHeight=(box.max.y-box.min.y)/.79;this.fitWidth=(box.max.x-box.min.x)/.9;this.updateFrustum();this.invalidate();if(commit)this.commit();}
  updateFrustum(){const half=Math.max(this.fitHeight||8,(this.fitWidth||0)/(this.width/this.height))/2;this.camera.top=half;this.camera.bottom=-half;this.camera.left=-half*this.width/this.height;this.camera.right=-this.camera.left;this.camera.updateProjectionMatrix();}
  orbit(dx,dy){const offset=this.camera.position.clone().sub(this.target),r=offset.length();let az=Math.atan2(offset.y,offset.x)-dx*.007,el=Math.asin(offset.z/r)+dy*.007;el=clamp(el,-1.48,1.48);this.camera.up.set(0,0,1);this.camera.position.copy(this.target).add(V(Math.cos(az)*Math.cos(el),Math.sin(az)*Math.cos(el),Math.sin(el)).multiplyScalar(r));this.camera.lookAt(this.target);}
  pan(dx,dy){const s=(this.camera.top-this.camera.bottom)/this.camera.zoom/this.height;const right=V(1,0,0).applyQuaternion(this.camera.quaternion),up=V(0,1,0).applyQuaternion(this.camera.quaternion);const delta=right.multiplyScalar(-dx*s).add(up.multiplyScalar(dy*s));this.camera.position.add(delta);this.target.add(delta);}
  zoom(factor){this.camera.zoom=clamp(this.camera.zoom/factor,.15,12);this.camera.updateProjectionMatrix();}
  commit(){if(this.data){const viewport={three_v1:this.viewport()};this.data.viewport={...this.data.viewport,...viewport};this.callbacks.viewport?.(viewport,this.data);}}
  project(position){const p=position.clone().project(this.camera);return {x:(p.x+1)*this.width/2,y:(1-p.y)*this.height/2,z:p.z,visible:p.z>=-1&&p.z<=1};}
  pointPosition(pathId,entryId){const n=this.nodes.find(n=>n.path.id===pathId&&n.point.entry_id===entryId);if(!n)return null;const p=this.project(n.position),r=this.canvas.getBoundingClientRect();return {x:p.x+r.left,y:p.y+r.top};}
  pick(x,y){const r=this.canvas.getBoundingClientRect();this.pointer.set((x-r.left)/r.width*2-1,-(y-r.top)/r.height*2+1);this.camera.updateMatrixWorld();this.raycaster.setFromCamera(this.pointer,this.camera);
    // Analytic screen-circle hit area matches the constant-size node (including its
    // antialiased edge), independent of Sprite's rectangular texture hit test.
    const candidates=this.nodes.filter(n=>this.pickObjects.includes(n.sprite)).map(n=>{const p=this.project(n.position);return {n,p,d:Math.hypot(x-r.left-p.x,y-r.top-p.y)};}).filter(v=>v.p.visible&&v.d<12).sort((a,b)=>a.d-b.d||a.p.z-b.p.z);
    return candidates[0]?.n||null;}
  layoutLabels(){const occupied=[];
    for(const a of this.axisLabels){const p=this.project(a.position);a.el.style.left=p.x+'px';a.el.style.top=p.y+'px';}
    const origin=this.overlay.getBoundingClientRect();
    for(const a of this.axisLabels){const r=a.el.getBoundingClientRect();occupied.push({x:r.left-origin.left,y:r.top-origin.top,w:r.width,h:r.height});}
    for(const n of [...this.nodes].sort((a,b)=>Number(b.point.selected)-Number(a.point.selected))){const p=this.project(n.position),w=n.label.offsetWidth||68,h=40;
      const candidates=[[12,-h-12],[-w-12,-h-12],[12,12],[-w-12,12],[12,-h-58],[-w-12,50]];let best=null,bestScore=Infinity;
      for(const [dx,dy] of candidates){const x=clamp(p.x+dx,6,this.width-w-6),y=clamp(p.y+dy,6,this.height-h-6);const b={x,y,w,h};let score=0;for(const o of occupied)score+=Math.max(0,Math.min(x+w,o.x+o.w)-Math.max(x,o.x))*Math.max(0,Math.min(y+h,o.y+o.h)-Math.max(y,o.y));if(score<bestScore){best=b;bestScore=score;}}
      n.label.style.transform=`translate(${best.x}px,${best.y}px)`;n.label.style.display=p.visible?'':'none';occupied.push(best);n.labelBox=best;
    }
    // Keep the tooltip off the energy/title/tick text as well as node labels.
    const node=this.hover||this.nodes.find(n=>n.point.selected);this.layoutTooltip(node,occupied);
  }
  layoutTooltip(n,occupied=[]){this.tooltip.replaceChildren();this.tooltip.hidden=!n;if(!n)return;
    const d=this.data,p=n.point,cn=d.language!=='en';this.tooltip.style.borderColor=p.selected?'#ffa469':n.path.color;
    const add=(text,cls)=>{const e=document.createElement('div');e.textContent=text;if(cls)e.className=cls;this.tooltip.append(e);};
    add(n.path.label+' · '+p.label_short,'tooltip-title');add(this.energySymbol+'  '+p.value_label+' '+d.unit_label,'tooltip-energy');
    add((cn?'体系能量':'System energy')+'  '+(finite(p.absolute_hartree)?p.absolute_hartree.toFixed(6):'—')+' Eh');
    const dependencies=[...(p.dependencies||[]),...(p.reference_dependencies||[])];const seen=new Set(),sources=[];
    for(const dep of dependencies){const key=JSON.stringify(dep);if(seen.has(key))continue;seen.add(key);const s=d.sources.find(s=>s[0]===dep.source_file_id),job=d.jobs?.find(j=>j[0]===dep.job_id&&j[1]===dep.source_file_id);sources.push((s?.[1]||dep.source_label||'—')+' · Job '+(job?.[2]||dep.job_id||'—')+' · '+(cn?'行 ':'line ')+(dep.source_line||'—'));}
    if(sources.length>1){const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=(cn?'多个来源':'Multiple sources')+' ('+sources.length+')';details.append(summary);for(const source of sources){const e=document.createElement('div');e.textContent=source;details.append(e);}this.tooltip.append(details);}else add(sources[0]||(cn?'无来源':'No source'),'tooltip-source');
    const p2=this.project(n.position),w=this.tooltip.offsetWidth||250,h=this.tooltip.offsetHeight||120;let best=null,score=Infinity;
    for(const [dx,dy] of [[42,-h/2],[-w-32,-h/2],[42,55],[-w-32,55],[0,-h-65],[0,80]]){const x=clamp(p2.x+dx,8,this.width-w-8),y=clamp(p2.y+dy,8,this.height-h-8);let overlap=0;for(const b of occupied)overlap+=Math.max(0,Math.min(x+w,b.x+b.w)-Math.max(x,b.x))*Math.max(0,Math.min(y+h,b.y+b.h)-Math.max(y,b.y));if(overlap<score){score=overlap;best={x,y};}}
    this.tooltip.style.left=best.x+'px';this.tooltip.style.top=best.y+'px';
  }
  mountCube(on){if(!this.cubeHost)return;this.cubeHost.replaceChildren();this.cubeHost.classList.remove('rf-placeholder');this.cubeHost.setAttribute('aria-label','Camera orientation');
    this.cubeCanvas=document.createElement('canvas');this.cubeCanvas.width=300;this.cubeCanvas.height=310;this.cubeCanvas.style.width='100%';this.cubeCanvas.style.height='100%';this.cubeHost.append(this.cubeCanvas);
    on(this.cubeCanvas,'pointerdown',e=>e.stopPropagation());on(this.cubeCanvas,'click',e=>{e.stopPropagation();const r=this.cubeCanvas.getBoundingClientRect(),x=(e.clientX-r.left)*150/r.width,y=(e.clientY-r.top)*155/r.height;const axis=(this.cubeTargets||[]).find(a=>Math.hypot(a.x-x,a.y-y)<18);let direction=axis?.direction;if(!direction){const face=(this.cubeFaces||[]).find(f=>{let inside=false;for(let i=0,j=f.points.length-1;i<f.points.length;j=i++){const a=f.points[i],b=f.points[j];if((a.y>y)!==(b.y>y)&&x<(b.x-a.x)*(y-a.y)/(b.y-a.y)+a.x)inside=!inside;}return inside;});direction=face?.direction;}if(direction)this.axisView(direction);});
  }
  axisView(direction){const distance=this.camera.position.distanceTo(this.target);this.camera.up.set(...(Math.abs(direction[2])>.9?[0,1,0]:[0,0,1]));this.camera.position.copy(this.target).add(V(...direction).multiplyScalar(distance));this.camera.lookAt(this.target);this.invalidate();this.commit();}
  drawCube(){if(!this.cubeCanvas)return;const ctx=this.cubeCanvas.getContext('2d');ctx.setTransform(2,0,0,2,0,0);ctx.clearRect(0,0,150,155);const q=this.camera.quaternion.clone().invert(),project=p=>{const v=p.clone().applyQuaternion(q);return {x:72+v.x*38,y:86-v.y*38,z:v.z};};
    const faces=[{direction:[1,0,0],vertices:[[.5,-.5,-.5],[.5,.5,-.5],[.5,.5,.5],[.5,-.5,.5]]},{direction:[-1,0,0],vertices:[[-.5,-.5,-.5],[-.5,-.5,.5],[-.5,.5,.5],[-.5,.5,-.5]]},{direction:[0,1,0],vertices:[[-.5,.5,-.5],[-.5,.5,.5],[.5,.5,.5],[.5,.5,-.5]]},{direction:[0,-1,0],vertices:[[-.5,-.5,-.5],[.5,-.5,-.5],[.5,-.5,.5],[-.5,-.5,.5]]},{direction:[0,0,1],vertices:[[-.5,-.5,.5],[.5,-.5,.5],[.5,.5,.5],[-.5,.5,.5]]},{direction:[0,0,-1],vertices:[[-.5,-.5,-.5],[-.5,.5,-.5],[.5,.5,-.5],[.5,-.5,-.5]]}].map(f=>({...f,points:f.vertices.map(p=>project(V(...p))),depth:project(V(...f.direction)).z})).sort((a,b)=>a.depth-b.depth);
    this.cubeFaces=[];for(const f of faces){ctx.beginPath();f.points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();ctx.fillStyle=this.data?.dark?'rgba(132,105,194,.20)':'rgba(132,105,194,.18)';ctx.strokeStyle='#8d73c1';ctx.fill();ctx.stroke();if(f.depth>0)this.cubeFaces.unshift(f);}
    const origin=project(V());this.cubeTargets=[];for(const [name,vector,c] of [['X',[1,0,0],'#b488ff'],['Y',[0,1,0],'#ffb268'],['Z',[0,0,1],'#63b9ff']]){const p=project(V(...vector).multiplyScalar(1.4));ctx.strokeStyle=c;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(origin.x,origin.y);ctx.lineTo(p.x,p.y);ctx.stroke();ctx.fillStyle=c;ctx.beginPath();ctx.arc(p.x,p.y,3,0,Math.PI*2);ctx.fill();ctx.font='bold 15px Segoe UI';ctx.fillText(name,p.x+5,p.y-5);this.cubeTargets.push({...p,direction:vector});}
  }
  resize(){if(!this.renderer)return;this.width=Math.max(this.host.clientWidth,1);this.height=Math.max(this.host.clientHeight,1);this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2.5));this.renderer.setSize(this.width,this.height,false);this.updateFrustum();this.group.traverse(o=>{if(o.material?.uniforms?.resolution)o.material.uniforms.resolution.value.set(this.width,this.height);});this.invalidate();}
  invalidate(){if(!this.visible||document.hidden||this.frame)return;this.frame=requestAnimationFrame(()=>{this.frame=0;this.draw();});}
  cancelFrame(){if(this.frame)cancelAnimationFrame(this.frame);this.frame=0;}
  draw(){if(!this.visible)return;this.camera.updateMatrixWorld(true);const pixel=(this.camera.top-this.camera.bottom)/this.camera.zoom/this.height;for(const n of this.nodes){n.sprite.scale.setScalar(pixel*(n.point.selected?18:16));if(n.ring)n.ring.scale.setScalar(pixel*38);}this.renderer.render(this.scene,this.camera);this.frames++;this.layoutLabels();this.drawCube();}
  capture(){this.draw();const canvas=document.createElement('canvas');canvas.width=1600;canvas.height=1000;const ctx=canvas.getContext('2d'),ratio=Math.min(1600/this.width,1000/this.height);ctx.fillStyle=this.data.visual_style?.background||'#100d1d';ctx.fillRect(0,0,1600,1000);ctx.translate((1600-this.width*ratio)/2,(1000-this.height*ratio)/2);ctx.scale(ratio,ratio);ctx.drawImage(this.canvas,0,0,this.width,this.height);
    ctx.beginPath();ctx.rect(0,0,this.width,this.height);ctx.clip();
    const origin=this.host.getBoundingClientRect();
    const label=(el,vertical=false)=>{if(getComputedStyle(el).display==='none')return;const r=el.getBoundingClientRect(),s=getComputedStyle(el);ctx.save();ctx.fillStyle=s.color;ctx.font=s.fontWeight+' '+s.fontSize+' '+s.fontFamily;ctx.textAlign='center';ctx.textBaseline='middle';ctx.translate(r.x-origin.x+r.width/2,r.y-origin.y+r.height/2);if(vertical)ctx.rotate(-Math.PI/2);ctx.fillText(el.textContent,0,0);ctx.restore();};
    for(const a of this.axisLabels)label(a.el,a.el.classList.contains('z-title'));
    for(const n of this.nodes)if(n.label.style.display!=='none')for(const el of n.label.children)label(el);
    for(const card of this.missingLabels||[]){const r=card.getBoundingClientRect(),x=r.left-origin.x,y=r.top-origin.y;ctx.save();ctx.fillStyle=this.data.dark?'rgba(44,31,25,.94)':'rgba(255,247,239,.96)';ctx.strokeStyle=card.style.getPropertyValue('--missing-color')||'#c76532';ctx.lineWidth=1.5;ctx.beginPath();ctx.roundRect(x,y,r.width,r.height,6);ctx.fill();ctx.stroke();ctx.fillStyle=this.data.dark?'#fff1e6':'#542b19';ctx.font='600 13px Segoe UI';ctx.textAlign='left';ctx.textBaseline='middle';ctx.fillText(card.textContent,x+9,y+r.height/2);ctx.restore();}
    return canvas.toDataURL('image/png');}
  diagnostics(){const corners=[];if(this.bounds)for(const x of [this.bounds.min.x,this.bounds.max.x])for(const y of [this.bounds.min.y,this.bounds.max.y])for(const z of [this.bounds.min.z,this.bounds.max.z])corners.push(this.project(V(x,y,z)));return {renderer:'Three.js',three_version:T.REVISION,projection:'orthographic',frames:this.frames,raf_pending:!!this.frame,listeners:this.listeners.length,objects:this.group.children.length,pick_objects:this.pickObjects.length,labels:this.nodes.length,geometries:this.renderer.info.memory.geometries,textures:this.renderer.info.memory.textures,viewport:this.viewport(),migration:this.migration||null,z_range:[this.zmin,this.zmax],extent:this.extent,bounds:corners,curtains:this.group.children.filter(o=>o.userData.decoration==='curtain').length};}
  dispose(){this.cancelFrame();clearTimeout(this.wheelTimer);this.listeners.forEach(fn=>fn());this.listeners=[];disposeTree(this.group);this.renderer.dispose();this.renderer.forceContextLoss();this.canvas.remove();this.overlay.remove();this.cubeHost?.replaceChildren();}
}
