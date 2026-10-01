export {};
declare global {
  interface Window {
    astra:{invoke:(operation:string,args?:any)=>Promise<any>;input:(message:any)=>void;subscribe:(callback:(message:any)=>void)=>()=>void};
  }
}
