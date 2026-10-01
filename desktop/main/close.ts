export type CloseChoice='cancel'|'keep'|'stop';

/** Serialize native close/quit events; stop must finish before allowing exit. */
export class CloseRequest {
  private pending:Promise<boolean>|null=null;
  constructor(private running:()=>Promise<boolean>,private choose:()=>Promise<CloseChoice>,
              private stop:()=>Promise<unknown>,private report:(error:unknown)=>Promise<unknown>){}
  request():Promise<boolean>{
    if(this.pending)return this.pending;
    this.pending=this.decide().finally(()=>{this.pending=null;});return this.pending;
  }
  private async decide(){
    try{
      if(!await this.running())return true;
      const choice=await this.choose();
      if(choice==='cancel')return false;
      if(choice==='stop')await this.stop();
      return true;
    }catch(error){await this.report(error);return false;}
  }
}
