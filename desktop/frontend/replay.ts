import {artifact} from './viewer';

export interface ReplayInfo {id:string|null;name?:string;events?:string;active:boolean;ready:boolean;kind?:'fragmented'|'file';generation?:string;duration:number;offset?:number;mime?:string;url?:string;error?:string|null}
interface Segment {index:number;start:number;end:number}
const current=(video:HTMLVideoElement,info:ReplayInfo)=>Math.max(0,video.currentTime-(info.offset??0));

/** Playback only: never issues engine, recording, agent or container commands. */
export class ReplayViewer {
  info:ReplayInfo={id:null,active:false,ready:false,duration:0};
  private source:MediaSource|null=null;
  private buffer:SourceBuffer|null=null;
  private url:string|null=null;
  private abort=new AbortController();
  private serial=0;
  private next=-1;
  private timer:ReturnType<typeof setTimeout>|undefined;
  private stopped=true;
  constructor(private video:HTMLVideoElement,private changed:(info:ReplayInfo)=>void,private failed:(message:string)=>void){}
  get position(){return current(this.video,this.info);}
  private async bytes(part:string,info=this.info){
    const response=await fetch(`astra://app/replay/${info.id}/${info.generation}/${part}`,{signal:this.abort.signal});
    if(!response.ok)throw new Error('Recording changed while loading replay. Seek again to refresh it.');
    return response.arrayBuffer();
  }
  private event(target:EventTarget,name:string,run:()=>void){
    const signal=this.abort.signal;
    return new Promise<void>((resolve,reject)=>{
      const done=()=>{cleanup();resolve();};
      const fail=()=>{cleanup();reject(new Error('Could not load recorded video'));};
      const aborted=()=>{cleanup();reject(new DOMException('Replay cancelled','AbortError'));};
      const timer=setTimeout(fail,15000);
      const cleanup=()=>{clearTimeout(timer);target.removeEventListener(name,done);target.removeEventListener('error',fail);signal.removeEventListener('abort',aborted);};
      target.addEventListener(name,done,{once:true});target.addEventListener('error',fail,{once:true});signal.addEventListener('abort',aborted,{once:true});
      try{run();}catch(error){cleanup();reject(error);}
    });
  }
  private append(data:ArrayBuffer){return this.event(this.buffer!,'updateend',()=>this.buffer!.appendBuffer(data));}
  private contains(time:number){
    for(let i=0;i<this.video.buffered.length;i++)if(time>=this.video.buffered.start(i)&&time<this.video.buffered.end(i)-.015)return true;
    return false;
  }
  private async seekFrame(time:number){
    if(Math.abs(this.video.currentTime-time)<.001&&!this.video.seeking)return;
    await this.event(this.video,'seeked',()=>this.video.currentTime=time);
  }
  async seek(info:ReplayInfo,position:number,play=false){
    if(!info.ready||!info.id)throw new Error('Waiting for completed recording frames');
    const target=Math.max(0,Math.min(position,info.duration-.025))+(info.offset??0);
    if(!this.stopped&&info.id===this.info.id&&info.generation===this.info.generation&&!this.buffer?.updating&&(info.kind==='file'||this.contains(target))){
      if(!play)this.video.pause();
      await this.seekFrame(target);if(play)await this.video.play();return;
    }
    this.close();this.stopped=false;this.info=info;this.changed(info);
    this.abort=new AbortController();const serial=this.serial;
    if(info.kind==='file'){
      await this.event(this.video,'loadedmetadata',()=>{this.video.src=artifact(info.url!);this.video.load();});
    }else{
      if(!MediaSource.isTypeSupported(info.mime!))throw new Error('This recording codec is not supported by the viewer');
      this.source=new MediaSource();this.url=URL.createObjectURL(this.source);
      await this.event(this.source,'sourceopen',()=>{this.video.src=this.url!;});
      if(serial!==this.serial)return;
      this.buffer=this.source.addSourceBuffer(info.mime!);
      this.source.duration=info.duration+(info.offset??0);
      await this.append(await this.bytes('init'));
      const segments:Segment[]=await window.astra.invoke('replay-index',{id:info.id,generation:info.generation,time:position});
      for(const segment of segments){
        if(serial!==this.serial)return;
        await this.append(await this.bytes(String(segment.index)));this.next=segment.index;
      }
    }
    if(serial!==this.serial)return;
    // Audio/video buffered intersections can start a few samples after the GOP.
    const low=this.video.buffered.length?this.video.buffered.start(0):0;
    const high=this.video.buffered.length?this.video.buffered.end(this.video.buffered.length-1)-.015:target;
    await this.seekFrame(info.kind==='file'?target:Math.max(low,Math.min(target,high)));
    if(play)await this.video.play();else this.video.pause();
    this.schedule(serial);
  }
  async play(){
    const info:ReplayInfo=await window.astra.invoke('replay-info',{id:this.info.id});
    if(info.generation!==this.info.generation||info.kind!==this.info.kind)await this.seek(info,this.position,true);
    else await this.video.play();
  }
  pause(){this.video.pause();}
  private schedule(serial:number){
    this.timer=setTimeout(()=>void this.pump(serial),700);
  }
  private async pump(serial:number){
    try{
      const info:ReplayInfo=await window.astra.invoke('replay-info',{id:this.info.id});
      if(serial!==this.serial||this.stopped)return;
      this.changed(info);
      if(info.generation!==this.info.generation||info.kind!==this.info.kind){
        // Preserve a paused picture during finalization; switch on play/seek.
        if(!this.video.paused){await this.seek(info,this.position,true);return;}
      }else{
        this.info=info;
        if(this.buffer&&this.source?.readyState==='open'){
          const now=this.video.currentTime;
          if(this.buffer.buffered.length&&this.buffer.buffered.start(0)<now-15)
            await this.event(this.buffer,'updateend',()=>this.buffer!.remove(0,now-10));
          const end=this.buffer.buffered.length?this.buffer.buffered.end(this.buffer.buffered.length-1):now;
          if(!this.video.paused&&end-now<6){
            const segments:Segment[]=await window.astra.invoke('replay-index',{id:info.id,generation:info.generation,after:this.next});
            for(const segment of segments){
              if(serial!==this.serial)return;
              await this.append(await this.bytes(String(segment.index)));this.next=segment.index;
            }
          }
          if(!info.active&&this.position>=info.duration-.035)this.video.pause();
        }
      }
    }catch(error){if(serial===this.serial&&!this.stopped)this.failed((error as Error).message);}
    if(serial===this.serial&&!this.stopped)this.schedule(serial);
  }
  close(){
    this.stopped=true;this.serial++;clearTimeout(this.timer);this.abort.abort();
    this.video.pause();this.video.removeAttribute('src');this.video.load();
    if(this.url)URL.revokeObjectURL(this.url);
    this.url=null;this.source=null;this.buffer=null;this.next=-1;
  }
}
