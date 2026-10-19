/* Verified source/job coordinates only. Bonds are display heuristics from Python. */
import * as T from './vendor/three.module.min.js';
const colors={1:'#f4f1ff',6:'#aaa9bd',7:'#5388fa',8:'#f34c51',9:'#83db8b',15:'#eba24b',16:'#e8d364',17:'#80d28c',35:'#b66d4e',53:'#9873cb'};
const disposeGroup=root=>{const geometries=new Set(),materials=new Set();root.traverse(o=>{if(o.geometry)geometries.add(o.geometry);if(o.material)materials.add(o.material);});geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());root.clear();};
export class MoleculeView {
  constructor(host){this.host=host;this.key=null;this.frame=0;this.frames=0;this.visible=true;this.listeners=[];
    this.renderer=new T.WebGLRenderer({antialias:true,alpha:true});this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2.5));this.renderer.outputColorSpace=T.SRGBColorSpace;
    this.canvas=this.renderer.domElement;this.canvas.className='molecule-canvas';host.prepend(this.canvas);
    this.scene=new T.Scene();this.group=new T.Group();this.scene.add(this.group);
    this.scene.add(new T.AmbientLight(0xffffff,2));const key=new T.DirectionalLight(0xffffff,3.5);key.position.set(-3,5,8);this.scene.add(key);
    this.camera=new T.OrthographicCamera(-3,3,2,-2,.01,1000);this.camera.position.set(0,0,30);
    const on=(el,type,fn,opts)=>{el.addEventListener(type,fn,opts);this.listeners.push(()=>el.removeEventListener(type,fn,opts));};
    on(this.canvas,'pointerdown',e=>{if(e.button!==0)return;this.drag={x:e.clientX,y:e.clientY};this.canvas.setPointerCapture(e.pointerId);e.stopPropagation();});
    on(this.canvas,'pointermove',e=>{if(!this.drag)return;this.group.rotation.y+=(e.clientX-this.drag.x)*.012;this.group.rotation.x+=(e.clientY-this.drag.y)*.012;this.drag={x:e.clientX,y:e.clientY};this.invalidate();});
    on(this.canvas,'pointerup',()=>{this.drag=null;});on(this.canvas,'pointercancel',()=>{this.drag=null;});
    on(this.canvas,'wheel',e=>{e.preventDefault();e.stopPropagation();this.camera.zoom=Math.max(.3,Math.min(5,this.camera.zoom*Math.exp(-e.deltaY*.001)));this.camera.updateProjectionMatrix();this.invalidate();},{passive:false});
    on(this.canvas,'dblclick',()=>{this.group.rotation.set(0,0,0);this.camera.zoom=1;this.camera.updateProjectionMatrix();this.invalidate();});
    on(document,'visibilitychange',()=>{if(document.hidden)this.cancel();else this.invalidate();});
    this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(host);this.resize();
  }
  setData(structure,dark){const key=structure?.status==='available'?[structure.source_sha256,structure.job_id,structure.line_start,structure.line_end].join('/'):'empty';
    this.renderer.setClearColor(dark?'#100d1b':'#f7f3fc',1);
    if(key!==this.key){this.key=key;disposeGroup(this.group);this.group.rotation.set(0,0,0);this.camera.zoom=1;
      if(structure?.status==='available'){
        const positions=structure.atoms.map(a=>new T.Vector3(...a.xyz)),box=new T.Box3().setFromPoints(positions),center=box.getCenter(new T.Vector3());positions.forEach(p=>p.sub(center));
        const materials=new Map();const material=z=>{if(!materials.has(z))materials.set(z,new T.MeshPhongMaterial({color:colors[z]||'#a3afbd',shininess:65,specular:0x999999}));return materials.get(z);};
        const sphere=new T.SphereGeometry(1,20,14);
        for(let i=0;i<positions.length;i++){const atom=structure.atoms[i],mesh=new T.Mesh(sphere,material(atom.atomic_number));mesh.position.copy(positions[i]);mesh.scale.setScalar(atom.atomic_number===1?.20:.31);this.group.add(mesh);}
        const axis=new T.Vector3(0,1,0),cylinder=new T.CylinderGeometry(.085,.085,1,10);
        for(const [a,b] of structure.bonds||[]){const start=positions[a],end=positions[b];if(!start||!end)continue;const middle=start.clone().add(end).multiplyScalar(.5);
          for(const [p,q,z] of [[start,middle,structure.atoms[a].atomic_number],[middle,end,structure.atoms[b].atomic_number]]){const direction=q.clone().sub(p),mesh=new T.Mesh(cylinder,material(z));mesh.scale.y=direction.length();mesh.quaternion.setFromUnitVectors(axis,direction.normalize());mesh.position.copy(p).add(q).multiplyScalar(.5);this.group.add(mesh);}}
        this.modelSize=box.getSize(new T.Vector3()).addScalar(.8);this.resize();
      }
    }this.canvas.hidden=structure?.status!=='available';
    // Three initializes an inline display:block; explicitly clear the old frame
    // when a valid model is unavailable (the HTML hidden rule alone loses to it).
    this.canvas.style.display=this.canvas.hidden?'none':'block';this.invalidate();
  }
  setVisible(v){this.visible=v;if(v)this.invalidate();else this.cancel();}
  resize(){const w=Math.max(this.host.clientWidth,1),h=Math.max(this.host.clientHeight,1);this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2.5));this.renderer.setSize(w,h,false);const aspect=w/h,s=this.modelSize||new T.Vector3(3,2,2),half=Math.max(s.y/.72,s.x/aspect/.65,s.z/.72)/2;this.camera.left=-half*aspect;this.camera.right=half*aspect;this.camera.top=half;this.camera.bottom=-half;this.camera.updateProjectionMatrix();this.invalidate();}
  cancel(){if(this.frame)cancelAnimationFrame(this.frame);this.frame=0;}
  invalidate(){if(this.frame||!this.visible||document.hidden)return;this.frame=requestAnimationFrame(()=>{this.frame=0;if(this.visible&&!this.canvas.hidden){this.renderer.render(this.scene,this.camera);this.frames++;}});}
  diagnostics(){return {key:this.key,objects:this.group.children.length,geometries:this.renderer.info.memory.geometries,frames:this.frames,raf:!!this.frame,rotation:this.group.rotation.toArray(),zoom:this.camera.zoom};}
  dispose(){this.cancel();this.observer.disconnect();this.listeners.forEach(fn=>fn());disposeGroup(this.group);this.renderer.dispose();this.renderer.forceContextLoss();this.canvas.remove();}
}
