<script lang="ts">
  import Icon from './Icon.svelte';
  export let events:any[]=[];
  export let clocks:any=null;
  export let active:any=null;
  export let showComments=true,showActions=false,showClocks=true;
  const time=(seconds:number)=>{const n=Math.floor(Math.max(0,seconds??0));return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(x=>String(x).padStart(2,'0')).join(':');};
  const icon=(op:string)=>/move|jump|go|approach|revisit|navigate|air/.test(op)?'arrow':/observe|look|scan|inspect/.test(op)?'monitor':/save|load/.test(op)?'folder':/record/.test(op)?'record':/knowledge|journal|read/.test(op)?'atlas':/ui|choose|click|interact/.test(op)?'cursor':'control';
  $: comments=events.filter(e=>e.kind==='comment').slice(-3);
  $: actions=Array.from(new Map(events.filter(e=>e.kind==='action').map(e=>[e.action_id,e])).values()).sort((a,b)=>Number(a.state==='active')-Number(b.state==='active')||a.time-b.time).slice(-4);
</script>

<div class="stream-overlays" aria-label="Session overlay">
  {#if showClocks&&clocks}<div class="overlay-clocks">
    <span title="Time with the agent connected" class:clock-active={clocks.wall_active}>Wall <b>{time(clocks.wall_seconds)}</b></span>
    <span title="Elapsed engine simulation time" class:clock-active={clocks.game_active}>Game <b>{time(clocks.game_seconds)}</b><Icon name={clocks.game_active?'play':'pause'} size={12}/></span>
  </div>{/if}
  {#if showActions&&actions.length}<div class="action-overlay" aria-label="Recent agent actions">
    {#each actions as row (row.action_id)}<div class="overlay-action" class:in-progress={row.state==='active'} class:failed={row.state==='error'||row.summary?.status==='blocked'}>
      <Icon name={icon(row.operation)} size={14}/><time>{time(row.wall_seconds)}</time><strong>{row.operation.replaceAll('_',' ')}</strong>
      <span>{row.state==='active'?(active?.phase??'Running'):row.reason??row.summary?.reason??row.feedback?.reason??'Done'}</span>
    </div>{/each}
  </div>{/if}
  {#if showComments&&comments.length}<div class="comment-overlay" aria-label="Agent commentary">
    {#each comments as row (row.id)}<div class="overlay-comment"><time>{time(row.wall_seconds)}</time><span>{row.text}</span></div>{/each}
  </div>{/if}
</div>
