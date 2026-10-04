/** Optional public OCI metadata. Native runtimes retain responsibility for auth,
 * downloading, digest verification and image storage; a lookup failure is harmless. */
export async function imageLayers(image:string):Promise<{digest:string;size:number}[]> {
  const slash=image.indexOf('/');if(slash<0)return [];
  const host=image.slice(0,slash),path=image.slice(slash+1);
  const at=path.indexOf('@'),colon=path.lastIndexOf(':');
  const repository=at>=0?path.slice(0,at):colon>=0?path.slice(0,colon):path;
  const reference=at>=0?path.slice(at+1):colon>=0?path.slice(colon+1):'latest';
  const local=/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host);
  const origin=`${local?'http':'https'}://${host}`;
  const signal=AbortSignal.timeout(10000);let token='';
  const accept='application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json';
  async function get(ref:string):Promise<any>{
    const url=`${origin}/v2/${repository}/manifests/${encodeURIComponent(ref)}`;
    const request=()=>fetch(url,{signal,headers:{Accept:accept,...(token?{Authorization:'Bearer '+token}:{})}});
    let response=await request();
    if(response.status===401&&!token){
      const challenge=response.headers.get('www-authenticate')??'';await response.body?.cancel();
      const fields=Object.fromEntries([...challenge.matchAll(/(realm|service|scope)="([^"]*)"/g)].map(m=>[m[1],m[2]]));
      if(!/^Bearer /i.test(challenge)||!fields.realm)throw Error('Registry authentication unavailable');
      const auth=new URL(fields.realm);if(auth.protocol!=='https:')throw Error('Insecure registry authentication');
      if(fields.service)auth.searchParams.set('service',fields.service);
      auth.searchParams.set('scope',fields.scope??`repository:${repository}:pull`);
      const r=await fetch(auth,{signal});if(!r.ok){await r.body?.cancel();throw Error('Registry token unavailable');}
      const result:any=await r.json();token=result.token??result.access_token;
      if(!token)throw Error('Registry token unavailable');response=await request();
    }
    if(!response.ok){await response.body?.cancel();throw Error('Registry manifest unavailable');}
    return response.json();
  }
  try{
    let manifest=await get(reference);
    if(manifest.manifests){const selected=manifest.manifests.find((m:any)=>m.platform?.os==='linux'&&m.platform?.architecture==='amd64');if(!selected)return [];manifest=await get(selected.digest);}
    return (manifest.layers??[]).filter((r:any)=>/^sha256:[a-f0-9]{64}$/.test(r.digest)&&Number.isSafeInteger(r.size)&&r.size>=0).map((r:any)=>({digest:r.digest,size:r.size}));
  }catch{return [];}
}
