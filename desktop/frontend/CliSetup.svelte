<script lang="ts">
  export let disabled=false,version='',digest='',warning:string|undefined;
  let state:any=null,error='',working=false,lastIdentity='',handledWarning='';
  $: if(version+'|'+digest!==lastIdentity){lastIdentity=version+'|'+digest;void refresh();}
  async function refresh(){try{state=await window.astra.invoke('cli-status');}catch(e){error=String(e);}}
  async function change(operation:string){
    working=true;error='';
    try{await window.astra.invoke(operation);handledWarning=warning??'';await refresh();}catch(e){error=(e as Error).message;}
    finally{working=false;}
  }
  $: usable=state?.enabled&&state.matches&&state.targetAvailable&&state.digest===digest;
</script>
<section class="cli-setup" aria-label="CLI command setup">
  <div class="cli-heading"><h3>CLI command</h3><code>astrabridge game observe</code></div>
  <p class="hint">{state?.removalPending?'Removal will finish when the running CLI command exits.':usable?'Enabled for this installation. The command follows successful runtime updates and uses the selected profile.':'Enable a permanent command for terminals and gameplay agents, then export the skill.'}</p>
  {#if state?.enabled&&!state.matches}<p class="hint">Currently linked to another installation: <code>{state.config}</code></p>{/if}
  {#if state?.enabled}<p class="hint cli-location" title={state.executable}>{state.executable}</p>{/if}
  {#if state?.enabled&&!state.pathReady}<p class="hint cli-guidance">{state.guidance}{#if state.shadowedBy} Current command: <code>{state.shadowedBy}</code>.{/if}</p>{/if}
  {#if state?.enabled&&!state.targetAvailable}<p class="cli-error">The application file is missing. Enable the command again to use this application.</p>{/if}
  {#if error||state?.error||(warning&&warning!==handledWarning)}<p class="cli-error" role="alert">{error||state?.error||warning}</p>{/if}
  <div class="toolbar">
    <button disabled={disabled||working} on:click={()=>change('cli-install')}>{usable?'Repair CLI command':state?.enabled&&!state.matches?'Use CLI for this installation':'Enable CLI command'}</button>
    <button disabled={disabled||working||(!state?.enabled&&!state?.removalPending)||!state?.matches} on:click={()=>change('cli-uninstall')}>{state?.removalPending?'Finish removing CLI command':'Remove CLI command'}</button>
  </div>
</section>
