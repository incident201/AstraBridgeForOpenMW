import {pointer} from './viewer';

type Motion={type:'relative'|'pointer';x:number;y:number};

export function mouseMotion(video:HTMLVideoElement,event:MouseEvent,uiMode:string|undefined):Motion|null{
  if(!uiMode||uiMode==='Gameplay')return {type:'relative',x:event.movementX,y:event.movementY};
  return pointer(video,event) as Motion|null;
}

// Keep total camera movement while sending at most one motion per display frame.
// Absolute cursor positions replace older positions; relative deltas accumulate.
export class MouseMotion {
  private pending:Motion|null=null;
  private frame:number|null=null;
  constructor(private send:(event:Motion)=>void,
    private schedule:(callback:FrameRequestCallback)=>number=requestAnimationFrame,
    private cancel:(id:number)=>void=cancelAnimationFrame){}
  push(event:Motion){
    if(event.type==='relative'&&this.pending?.type==='relative'){
      this.pending={type:'relative',x:this.pending.x+event.x,y:this.pending.y+event.y};
    }else this.pending=event;
    if(this.frame===null)this.frame=this.schedule(()=>{
      const pending=this.pending;this.frame=null;this.pending=null;
      if(pending)this.send(pending);
    });
  }
  clear(){if(this.frame!==null)this.cancel(this.frame);this.frame=null;this.pending=null;}
}
