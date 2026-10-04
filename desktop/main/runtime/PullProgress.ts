export interface PullStatus {
  type:'transfer'; phase:'connecting'|'downloading'|'unpacking'|'complete'|'failed';
  image:string; received:number; total:number|null; reused:number; speed:number;
  elapsed:number; idle:number; layers:number; completed:number;
}
export interface StageStatus {type:'stage';message:string}
export type Progress=(message:string|PullStatus|StageStatus)=>void;
const bytes=(value:string,unit:string)=>Number(value)*({b:1,B:1,KiB:1024,MiB:1024**2,GiB:1024**3,kB:1000,KB:1000,MB:1e6,GB:1e9}[unit]??1);
export const cleanTerminal=(text:string)=>text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/[^\x09\x0a\x0d\x20-\uFFFF]/g,'');

/** Native transfer counters, never simulated percentages. Unknown totals stay unknown. */
export class PullProgress {
  private rows=new Map<string,{current:number;total:number;done:boolean;reused:boolean}>();
  private finished=false; private buffer=''; private started=Date.now(); private changed=this.started; private sampled=this.started;
  private previous=0; private speed=0; private phase:PullStatus['phase']='connecting'; private timer:ReturnType<typeof setInterval>;
  constructor(private image:string,private emit:Progress=()=>{},layers:{digest:string;size:number}[]=[]){
    for(const row of layers)this.rows.set(row.digest.replace(/^sha256:/,'').slice(0,12),{current:0,total:row.size,done:false,reused:false});
    this.emit(this.status());this.timer=setInterval(()=>this.publish(),1000);this.timer.unref();
  }
  setLayers(layers:{digest:string;size:number}[]){
    for(const row of layers){const id=row.digest.replace(/^sha256:/,'').slice(0,12);
      this.rows.set(id,{current:0,total:row.size,done:false,reused:false});}
    this.publish();
  }
  feed=(chunk:string)=>{
    if(this.finished)return;
    this.buffer+=chunk;
    const lines=this.buffer.split(/[\r\n]/);this.buffer=lines.pop()??'';
    for(const raw of lines)this.line(cleanTerminal(raw).trim());
    if(this.buffer.length>16000)this.buffer=this.buffer.slice(-16000);
  };
  private line(line:string){
    if(!line)return;
    const match=line.match(/Copying blob (?:sha256:)?([a-f0-9]{12,64})/i);
    if(match){
      const id=match[1].slice(0,12),row={...(this.rows.get(id)??{current:0,total:0,done:false,reused:false})};
      const count=line.match(/([\d.]+)\s*([KMGT]?i?B|b)\s*\/\s*([\d.]+)\s*([KMGT]?i?B|b)/);
      const old=row.current;
      if(count){row.current=Math.max(row.current,bytes(count[1],count[2]));row.total=row.total||bytes(count[3],count[4]);}
      if(/skipped|already exists/i.test(line)){row.reused=true;row.done=true;row.current=0;}
      else if(/\bdone\b/i.test(line)){row.done=true;row.current=row.total||row.current;}
      if(row.total)row.current=Math.min(row.current,row.total);
      if(row.current!==old)this.changed=Date.now();
      if(row.done&&!this.rows.get(id)?.done)this.emit(line+'\n');
      this.rows.set(id,{...row});this.phase='downloading';
      return;
    }
    if(/Copying config|Writing manifest|Storing signatures/i.test(line))this.phase='unpacking';
    this.emit(line+'\n');this.publish();
  }
  status():PullStatus{
    const rows=[...this.rows.values()],now=Date.now();
    const received=rows.filter(r=>!r.reused).reduce((n,r)=>n+r.current,0);
    return {type:'transfer',phase:this.phase,image:this.image,received,total:rows.length&&rows.every(r=>r.total>0)?rows.filter(r=>!r.reused).reduce((n,r)=>n+r.total,0):null,
      reused:rows.filter(r=>r.reused).reduce((n,r)=>n+r.total,0),speed:this.speed,elapsed:(now-this.started)/1000,
      idle:(now-this.changed)/1000,layers:rows.length,completed:rows.filter(r=>r.done).length};
  }
  private publish(){
    const now=Date.now(),state=this.status();
    if(now-this.sampled>=750){this.speed=Math.max(0,state.received-this.previous)/((now-this.sampled)/1000);this.previous=state.received;this.sampled=now;}
    this.emit({...state,speed:this.speed});
  }
  finish(ok:boolean){
    clearInterval(this.timer);if(this.buffer)this.line(cleanTerminal(this.buffer));this.buffer='';
    this.phase=ok?'complete':'failed';this.publish();this.finished=true;
  }
}
