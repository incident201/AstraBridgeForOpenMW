<script lang="ts">
  import Icon from './Icon.svelte';
  import {createEventDispatcher} from 'svelte';
  export let src:string;
  export let markers:{ref:string;label:string;x:number;y:number}[]=[];
  export let selected:string|undefined=undefined;
  export let bounds:{left:number;right:number;top:number;bottom:number}|undefined=undefined;
  const dispatch=createEventDispatcher<{select:string}>();
  let width=0,height=0,aspect=680/645,pendingFit=true;
  $: imageWidth=Math.min(width,height*aspect);
  $: imageHeight=imageWidth/aspect;
  let zoom=1,x=0,y=0,viewport:HTMLDivElement,drag:{id:number;x:number;y:number}|null=null,previous='';
  $: if(src!==previous){previous=src;zoom=1;x=0;y=0;pendingFit=true;}
  $: if(pendingFit&&imageWidth>0&&imageHeight>0){pendingFit=false;fit();}
  function fit(){
    if(!bounds){zoom=1;x=0;y=0;return;}
    zoom=Math.max(1,Math.min(3,.82*width/(imageWidth*Math.max(.1,bounds.right-bounds.left)),.82*height/(imageHeight*Math.max(.1,bounds.bottom-bounds.top))));
    x=(.5-(bounds.left+bounds.right)/2)*imageWidth*zoom;y=(.5-(bounds.top+bounds.bottom)/2)*imageHeight*zoom;clamp();
  }
  function clamp(){const b=viewport.getBoundingClientRect();x=Math.max(-b.width*(zoom-1)/2,Math.min(b.width*(zoom-1)/2,x));y=Math.max(-b.height*(zoom-1)/2,Math.min(b.height*(zoom-1)/2,y));}
  function scale(next:number,event?:WheelEvent){
    const value=Math.max(1,Math.min(6,next)),ratio=value/zoom,b=viewport.getBoundingClientRect();
    x=x*ratio+(event?event.clientX-b.left-b.width/2:0)*(1-ratio);y=y*ratio+(event?event.clientY-b.top-b.height/2:0)*(1-ratio);zoom=value;clamp();
  }
  function down(event:PointerEvent){if(zoom<=1||event.button!==0||(event.target as Element).closest('button'))return;drag={id:event.pointerId,x:event.clientX,y:event.clientY};viewport.setPointerCapture(event.pointerId);}
  function move(event:PointerEvent){if(!drag||event.pointerId!==drag.id)return;x+=event.clientX-drag.x;y+=event.clientY-drag.y;drag={...drag,x:event.clientX,y:event.clientY};clamp();}
  function key(event:KeyboardEvent){
    if(['+','=','-','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))event.preventDefault();
    if(event.key==='+'||event.key==='=')scale(zoom*1.3);else if(event.key==='-')scale(zoom/1.3);else if(event.key==='0')fit();
    else if(event.key.startsWith('Arrow')){x+=event.key==='ArrowLeft'?40:event.key==='ArrowRight'?-40:0;y+=event.key==='ArrowUp'?40:event.key==='ArrowDown'?-40:0;clamp();}
  }
  export function focus(ref:string){const marker=markers.find(m=>m.ref===ref);if(marker){zoom=Math.max(zoom,2);x=(.5-marker.x)*imageWidth*zoom;y=(.5-marker.y)*imageHeight*zoom;clamp();viewport.focus();}}
  function loaded(event:Event){const image=event.currentTarget as HTMLImageElement;aspect=image.naturalWidth/image.naturalHeight;pendingFit=true;}
</script>
<div class="atlas-map">
  <!-- This keyboard/pointer surface pans only the retained map image. -->
  <!-- svelte-ignore a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
  <div class="atlas-canvas" class:draggable={zoom>1} bind:this={viewport} bind:clientWidth={width} bind:clientHeight={height} tabindex="0" role="region" aria-label="Travelled map. Use plus and minus to zoom, arrow keys to pan, zero to reset."
    on:pointerdown={down} on:pointermove={move} on:pointerup={()=>drag=null} on:lostpointercapture={()=>drag=null} on:keydown={key}
    on:wheel|preventDefault|nonpassive={event=>scale(zoom*(event.deltaY<0?1.15:1/1.15),event)}>
    <div class="atlas-image-stage" style:width={imageWidth+'px'} style:height={imageHeight+'px'} style:transform={`translate(-50%, -50%) translate(${x}px, ${y}px) scale(${zoom})`}>
      <img class="atlas-image" {src} alt="Map of travelled routes" draggable="false" on:load={loaded}>
      {#each markers.filter(m=>m.x>=0&&m.x<=1&&m.y>=0&&m.y<=1) as marker}<button class="atlas-marker" class:selected={selected===marker.ref} style:left={marker.x*100+'%'} style:top={marker.y*100+'%'} style:transform={`translate(-50%, -50%) scale(${1/zoom})`} aria-label={'Show point '+marker.label} aria-pressed={selected===marker.ref} title={marker.label} on:click={()=>dispatch('select',marker.ref)}></button>{/each}
    </div>
  </div>
  <div class="map-controls"><span>Scroll to zoom · drag to pan</span><div class="toolbar">
    <button aria-label="Zoom out" disabled={zoom<=1} on:click={()=>scale(zoom/1.3)}><Icon name="minus" size={16}/></button>
    <button class="map-reset" title="Fit the travelled area" on:click={fit}>Fit · {Math.round(zoom*100)}%</button>
    <button aria-label="Zoom in" disabled={zoom>=6} on:click={()=>scale(zoom*1.3)}><Icon name="plus" size={16}/></button>
  </div></div>
</div>
