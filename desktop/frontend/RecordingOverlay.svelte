<script lang="ts">
  import {onDestroy} from 'svelte';
  import StreamOverlay from './StreamOverlay.svelte';
  export let eventsPath:string|undefined;
  export let position=0;
  export let showComments=true,showActions=false,showClocks=true;
  let data:any=null,serial=0,lastPath:string|undefined,lastPosition=0;
  $: void update(eventsPath,position,showComments||showActions||showClocks);
  async function update(path:string|undefined,seconds:number,enabled:boolean){
    const request=++serial;
    if(path!==lastPath||seconds<lastPosition||seconds-lastPosition>1)data=null;
    lastPath=path;lastPosition=seconds;
    if(!path||!enabled){data=null;return;}
    try{
      const result=await window.astra.invoke('recording-timeline',{path,time:Math.max(0,seconds)});
      if(request===serial)data=result;
    }catch{if(request===serial)data=null;}
  }
  onDestroy(()=>serial++);
</script>

{#if data}<StreamOverlay events={data.events} clocks={data.clocks} {showComments} {showActions} {showClocks}/>{/if}
