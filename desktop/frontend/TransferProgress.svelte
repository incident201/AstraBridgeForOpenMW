<script lang="ts">
  import type {PullStatus} from '../main/runtime/PullProgress';
  export let status:PullStatus;
  const size=(n:number)=>n>=1024**3?(n/1024**3).toFixed(2)+' GiB':(n/1024**2).toFixed(1)+' MiB';
  const time=(n:number)=>n<60?Math.floor(n)+'s':Math.floor(n/60)+'m '+Math.floor(n%60)+'s';
  $: percent=status.total!==null&&status.total>0?Math.min(100,Math.floor(status.received/status.total*100)):null;
  $: title=({connecting:'Connecting to image registry',downloading:'Downloading runtime',unpacking:'Installing image layers',complete:'Runtime image ready',failed:'Runtime download failed'})[status.phase];
</script>
<div class="transfer-progress" role="status" aria-label="Runtime download progress">
  <div class="transfer-title"><strong>{title}</strong><span>{status.phase==='complete'?'Complete':percent!==null?percent+'%':''}</span></div>
  {#if percent===null&&status.phase!=='complete'}<progress max="100" aria-label="Image download"></progress>
  {:else}<progress max="100" value={status.phase==='complete'?100:percent??0} aria-label="Image download"></progress>{/if}
  <div class="transfer-counters"><span>{#if status.layers}{size(status.received)} received{#if status.total!==null}{' / '+size(status.total)}{/if}{:else}Size not reported by runtime{/if}</span><span>{status.phase==='downloading'?size(status.speed)+'/s · ':''}{time(status.elapsed)} elapsed</span></div>
  <div class="transfer-detail">{status.completed} / {status.layers||'…'} layers ready{#if status.reused>0} · {size(status.reused)} reused{/if}</div>
  {#if status.idle>=15&&status.phase!=='complete'&&status.phase!=='failed'}<p>No new download counters for {time(status.idle)}. The runtime may be waiting for the network or unpacking a layer.</p>{/if}
</div>
