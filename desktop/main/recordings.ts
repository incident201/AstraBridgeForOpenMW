import {readdir,readFile,realpath,stat,lstat} from 'node:fs/promises';
import {join,relative,sep,basename} from 'node:path';
import {createHash} from 'node:crypto';
import {RecordingTimeline} from './timeline';

/** Host-owned recordings stay available even when the runtime is absent. */
export class Recordings {
  private files=new Map<string,{root:string;path:string}>();
  private timelines=new Map<string,RecordingTimeline>();
  async timeline(path:string,seconds:number){
    const file=await this.path(path.split('/').pop()!);
    if(!file||!file.endsWith('.events.jsonl'))throw new Error('Recording timeline unavailable');
    if(!this.timelines.has(file)){
      if(this.timelines.size>=4)this.timelines.delete(this.timelines.keys().next().value!);
      this.timelines.set(file,new RecordingTimeline(file));
    }
    return this.timelines.get(file)!.at(seconds);
  }
  async replayEvents(root:string,name:string,subdirectory:string){
    if(typeof name!=='string'||basename(name)!==name||!name.endsWith('.mp4')||typeof subdirectory!=='string'||subdirectory&&!/^[a-f0-9]{32}$/.test(subdirectory))return undefined;
    const path=join(root,subdirectory,name.slice(0,-4)+'.events.jsonl');
    try{if((await lstat(path)).isFile())return this.artifact(root,path);}catch{}
    return undefined;
  }
  async path(id:string){
    const entry=this.files.get(id);if(!entry)return null;
    const root=await realpath(entry.root),path=await realpath(entry.path);
    const rel=relative(root,path);
    if(rel==='..'||rel.startsWith('..'+sep)||!rel)throw new Error('Recording outside its folder');
    return path;
  }
  private artifact(root:string,path:string){
    const id=createHash('sha256').update('host-recording:'+path).digest('hex').slice(0,32);
    this.files.set(id,{root,path});return '/v1/artifacts/'+id;
  }
  async list(root:string){
    const rows:any[]=[];
    const scan=async(directory:string,profileId:string)=>{
      let entries;try{entries=await readdir(directory,{withFileTypes:true});}catch(error){if((error as NodeJS.ErrnoException).code==='ENOENT')return;throw error;}
      for(const entry of entries){
        const path=join(directory,entry.name);
        if(directory===root&&entry.isDirectory()&&/^[a-f0-9]{32}$/.test(entry.name)){await scan(path,entry.name);continue;}
        if(!entry.isFile()||!entry.name.endsWith('.mp4')||entry.name.endsWith('.finalizing.mp4'))continue;
        const info=await stat(path),stem=path.slice(0,-4);
        let context:any={};
        try{if((await lstat(stem+'.context.json')).isFile())context=JSON.parse(await readFile(stem+'.context.json','utf8'));}catch{}
        const row:any={id:createHash('sha256').update(path).digest('hex').slice(0,32),name:entry.name,
          bytes:info.size,created:info.mtimeMs/1000,profile_id:profileId,
          profile_name:context.profile?.name??(profileId==='default'?'Default':profileId.slice(0,8)),video:this.artifact(root,path)};
        for(const [suffix,field] of [['.json','metadata'],['.encoder.json','encoder'],['.ffmpeg.log','diagnostics'],['.events.jsonl','events']]){
          try{const sidecar=stem+suffix;if((await lstat(sidecar)).isFile())row[field]=this.artifact(root,sidecar);}catch{}
        }
        rows.push(row);
      }
    };
    await scan(root,'default');return rows.sort((a,b)=>b.created-a.created);
  }
}
