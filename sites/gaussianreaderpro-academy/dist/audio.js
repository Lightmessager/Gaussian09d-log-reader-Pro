globalThis.AcademyAudio=(function(){
  let context,enabled=false,volume=.25;
  async function enable(value){enabled=value;if(value){try{context??=new (window.AudioContext||window.webkitAudioContext)();await context.resume();}catch{enabled=false;}}return enabled;}
  function play(type='click'){
    if(!enabled||!context||context.state!=='running'||document.hidden)return;
    const notes=type==='success'?[523.25,659.25,783.99]:type==='switch'?[392,523.25]:[660];
    notes.forEach((freq,i)=>{let o=context.createOscillator(),g=context.createGain(),at=context.currentTime+i*.07;o.type='sine';o.frequency.setValueAtTime(freq,at);g.gain.setValueAtTime(0,at);g.gain.linearRampToValueAtTime(volume*.13,at+.015);g.gain.exponentialRampToValueAtTime(.0001,at+.25);o.connect(g);g.connect(context.destination);o.start(at);o.stop(at+.28);o.onended=()=>{o.disconnect();g.disconnect();};});
  }
  return {enable,play,setVolume:v=>{volume=Math.max(0,Math.min(1,Number(v)||0));},isEnabled:()=>enabled};
})();
