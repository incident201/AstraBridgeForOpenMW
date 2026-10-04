/** One save attempt and one confirmation for concurrent Stop/close requests. */
export class StopSessionRequest {
 private pending:Promise<any>|null=null;
 constructor(private attempt:()=>Promise<any>,private confirm:(reason:string,prepared:boolean)=>Promise<boolean>,
             private discard:()=>Promise<any>,private cancel:(token?:string)=>Promise<any>){}
 request():Promise<any>{
  if(this.pending)return this.pending;
  this.pending=this.run().finally(()=>{this.pending=null;});return this.pending;
 }
 private async run(){
  try{return await this.attempt();}
  catch(error){
   const detail=(error as any).details;
   if(detail?.error!=='save_before_stop_failed')throw error;
   if(await this.confirm(detail.reason,Boolean(detail.token)))return this.discard();
   await this.cancel(detail.token);return {cancelled:true};
  }
 }
}
