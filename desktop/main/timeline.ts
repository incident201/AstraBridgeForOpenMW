import {open} from 'node:fs/promises';

interface State {comments:any[];actions:Map<string,any>}
const empty=():State=>({comments:[],actions:new Map()});
const clone=(s:State):State=>({comments:[...s.comments],actions:new Map(s.actions)});
function apply(state:State,row:any){
  if(row.kind==='snapshot')for(const event of row.events??[])apply(state,event);
  if(row.kind==='comment')state.comments=[...state.comments,row].slice(-3);
  if(row.kind==='action'){
    state.actions.delete(row.action_id);state.actions.set(row.action_id,row);
    const finished=[...state.actions.values()].filter(e=>e.state!=='active');
    for(const old of finished.slice(0,-4))state.actions.delete(old.action_id);
  }
}
function upperBound(rows:{at:number}[],at:number){
  let low=0,high=rows.length;
  while(low<high){const mid=(low+high)>>>1;if(rows[mid].at<=at)low=mid+1;else high=mid;}
  return low;
}

/** Incremental JSONL index: seeks replay a maximum of 127 event changes. */
export class RecordingTimeline {
  private cursor=0;private generation='';private loading:Promise<void>|null=null;
  private points:{at:number;row:any}[]=[];private clocks:{at:number;value:any}[]=[];
  private state=empty();private checkpoints:State[]=[empty()];
  constructor(private path:string){}
  private async scan(){
    const file=await open(this.path,'r');
    try{
      const info=await file.stat(),generation=String(info.dev)+':'+String(info.ino);
      if(this.generation!==generation||info.size<this.cursor){
        this.cursor=0;this.points=[];this.clocks=[];this.state=empty();this.checkpoints=[empty()];this.generation=generation;
      }
      // Only publish complete lines; a writer may be appending the final event.
      let pending=Buffer.alloc(0),position=this.cursor;
      const buffer=Buffer.alloc(64*1024);
      while(position<info.size){
        const {bytesRead}=await file.read(buffer,0,Math.min(buffer.length,info.size-position),position);
        if(!bytesRead)break;position+=bytesRead;pending=Buffer.concat([pending,buffer.subarray(0,bytesRead)]);
        let start=0,end;
        while((end=pending.indexOf(10,start))>=0){
          const line=pending.subarray(start,end);this.cursor+=end-start+1;start=end+1;
          if(line.length>65536)continue;
          let row;try{row=JSON.parse(line.toString('utf8'));}catch{continue;}
          const at=row.recording_seconds;
          if(typeof at!=='number'||!Number.isFinite(at)||at<0)continue;
          const last=this.clocks.at(-1)?.at??0;if(at<last)continue;
          if(Number.isFinite(row.wall_seconds)&&Number.isFinite(row.game_seconds))
            this.clocks.push({at,value:{wall_seconds:row.wall_seconds,game_seconds:row.game_seconds,wall_active:row.wall_active,game_active:row.game_active}});
          if(['snapshot','comment','action'].includes(row.kind)){
            this.points.push({at,row});apply(this.state,row);
            if(this.points.length%128===0)this.checkpoints.push(clone(this.state));
          }
        }
        pending=pending.subarray(start);
        if(pending.length>65536)throw new Error('Recording timeline line is too large');
      }
    }finally{await file.close();}
  }
  async at(seconds:number){
    if(!Number.isFinite(seconds)||seconds<0)throw new Error('Invalid recording position');
    if(!this.loading)this.loading=this.scan().finally(()=>this.loading=null);
    await this.loading;
    const count=upperBound(this.points,seconds),block=Math.floor(count/128),state=clone(this.checkpoints[block]);
    for(let i=block*128;i<count;i++)apply(state,this.points[i].row);
    const index=upperBound(this.clocks,seconds)-1,current=this.clocks[index],next=this.clocks[index+1];
    const clocks=current?{...current.value}:null;
    if(clocks&&next&&next.at>current.at){
      const t=(seconds-current.at)/(next.at-current.at);
      for(const key of ['wall_seconds','game_seconds'])clocks[key]+=Math.max(0,next.value[key]-clocks[key])*t;
    }
    return {events:[...state.comments,...state.actions.values()],clocks};
  }
}
