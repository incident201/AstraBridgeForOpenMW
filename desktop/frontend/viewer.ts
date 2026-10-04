export class Viewer {
  peer:RTCPeerConnection|null=null;
  private generation=0;
  private video:HTMLVideoElement|null=null;
  location:string|null=null;
  constructor(private lost:()=>void=()=>{}){}
  async start(video:HTMLVideoElement,quality:string){
    await this.close(false);
    const generation=this.generation;
    const check=()=>{if(generation!==this.generation)throw new DOMException('Viewer closed','AbortError');};
    try{await window.astra.invoke('live-start',{quality});}catch(error){check();throw error;}
    check();this.video=video;
    const peer=new RTCPeerConnection({iceServers:[]});this.peer=peer;
    peer.onconnectionstatechange=()=>{if(generation===this.generation&&peer.connectionState==='failed')this.lost();};
    const stream=new MediaStream();video.srcObject=stream;
    peer.ontrack=event=>{stream.addTrack(event.track);void video.play().catch(()=>{});};
    peer.addTransceiver('video',{direction:'recvonly'});peer.addTransceiver('audio',{direction:'recvonly'});
    await peer.setLocalDescription(await peer.createOffer());
    if(peer.iceGatheringState!=='complete')await new Promise<void>(resolve=>{
      const timer=setTimeout(resolve,3000);
      peer.addEventListener('icegatheringstatechange',()=>{if(peer.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});
    });
    check();
    let response:any;
    for(let attempt=0;attempt<12;attempt++){
      check();
      try{response=await window.astra.invoke('whep',{path:'/v1/runtime/live/whep',method:'POST',body:peer.localDescription!.sdp});break;}
      catch(error){check();if(attempt===11){peer.close();throw error;}await new Promise(resolve=>setTimeout(resolve,250));}
    }
    if(generation!==this.generation){peer.close();if(response.location)void window.astra.invoke('whep',{path:response.location,method:'DELETE'}).catch(()=>{});check();}
    this.location=response.location;
    try{await peer.setRemoteDescription({type:'answer',sdp:response.body});}catch(error){check();throw error;}check();
  }
  async close(stop=true){
    this.generation++;this.peer?.close();this.peer=null;
    if(this.video){this.video.srcObject=null;this.video=null;}
    const location=this.location;this.location=null;
    if(location)await window.astra.invoke('whep',{path:location,method:'DELETE'}).catch(()=>{});
    if(stop)await window.astra.invoke('live-stop').catch(()=>{});
  }
}

export function artifact(path:string){return path?.startsWith('/v1/artifacts/')?'astra-artifact://'+path.split('/').pop():'';}

export function pointer(video:HTMLVideoElement,event:MouseEvent){
  const box=video.getBoundingClientRect();const aspect=(video.videoWidth||1920)/(video.videoHeight||1080);
  const width=Math.min(box.width,box.height*aspect),height=width/aspect;
  const x=(event.clientX-box.left-(box.width-width)/2)/width,y=(event.clientY-box.top-(box.height-height)/2)/height;
  return x>=0&&x<=1&&y>=0&&y<=1?{type:'pointer',x,y}:null;
}
