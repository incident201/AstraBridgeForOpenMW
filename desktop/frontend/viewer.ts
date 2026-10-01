export class Viewer {
  peer:RTCPeerConnection|null=null;
  location:string|null=null;
  async start(video:HTMLVideoElement,quality:string){
    await this.close(false);
    await window.astra.invoke('live-start',{quality});
    const peer=new RTCPeerConnection({iceServers:[]});this.peer=peer;
    const stream=new MediaStream();video.srcObject=stream;
    peer.ontrack=event=>{stream.addTrack(event.track);void video.play().catch(()=>{});};
    peer.addTransceiver('video',{direction:'recvonly'});peer.addTransceiver('audio',{direction:'recvonly'});
    await peer.setLocalDescription(await peer.createOffer());
    if(peer.iceGatheringState!=='complete')await new Promise<void>(resolve=>{
      const timer=setTimeout(resolve,3000);
      peer.addEventListener('icegatheringstatechange',()=>{if(peer.iceGatheringState==='complete'){clearTimeout(timer);resolve();}});
    });
    let response:any;
    for(let attempt=0;attempt<12;attempt++){
      try{response=await window.astra.invoke('whep',{path:'/v1/runtime/live/whep',method:'POST',body:peer.localDescription!.sdp});break;}
      catch(error){if(attempt===11){peer.close();throw error;}await new Promise(resolve=>setTimeout(resolve,250));}
    }
    this.location=response.location;
    await peer.setRemoteDescription({type:'answer',sdp:response.body});
  }
  async close(stop=true){
    this.peer?.close();this.peer=null;
    if(this.location){await window.astra.invoke('whep',{path:this.location,method:'DELETE'}).catch(()=>{});this.location=null;}
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
