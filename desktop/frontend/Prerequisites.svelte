<script lang="ts">
  import Icon from './Icon.svelte';
  import type {PrerequisiteReport} from '../main/runtime/RuntimeBackend';
  export let report:PrerequisiteReport|null=null;
  export let checking=false;
  export let recheck:()=>Promise<void>;
  $: checks=report?.checks??(report?[{id:'containers',title:'Container runtime',status:report.available?'ok':'error',detail:report.message??report.version}]:[]);
  $: ordered=[...checks].sort((a,b)=>({error:0,warning:1,ok:2}[a.status]??3)-({error:0,warning:1,ok:2}[b.status]??3));
</script>

<div class="requirements-panel">
  <div class="section-heading"><div><h3>System requirements</h3><p class="hint">{checking?'Checking this computer…':report?.available?'Required host checks passed.':'Install or configure the components listed below, then check again.'}</p></div>
    <button disabled={checking} on:click={recheck}><Icon name="restart" size={17}/>{checking?'Checking…':'Check again'}</button>
  </div>
  <div class="requirements-list scroll-region" aria-label="System requirement results" aria-live="polite">
    {#each ordered as check}<div class="requirement" class:requirement-error={check.status==='error'}>
      <span class="requirement-state" class:passed={check.status==='ok'}>{check.status==='ok'?'Ready':check.status==='warning'?'Note':'Required'}</span>
      <div><strong>{check.title}</strong><p>{check.detail}</p>{#if 'remedy' in check&&check.remedy}<p class="requirement-remedy">{check.remedy}</p>{/if}</div>
    </div>{/each}
  </div>
  <p class="hint">Packages are installed by you or your administrator. GPU rendering and hardware encoding are verified separately inside the runtime.</p>
</div>

<style>
  .requirements-panel{flex:1;min-height:0;display:flex;flex-direction:column;gap:12px}
  .section-heading{margin:0;flex-shrink:0}.section-heading .hint{margin:5px 0 0}
  .requirements-list{flex:1;min-height:0;overflow:auto;padding-right:6px}
  .requirement{display:grid;grid-template-columns:72px minmax(0,1fr);gap:12px;padding:12px 0;border-bottom:1px solid #29374a;overflow-wrap:anywhere}
  .requirement p{font-size:13px;margin:5px 0 0;color:#abb9ce}.requirement .requirement-remedy{color:#e8cdb2;white-space:pre-wrap}
  .requirement-state{font-size:11px;color:#e4bb91;font-weight:600;padding-top:3px}.requirement-state.passed{color:#6ddcad}
  .requirement-error .requirement-state{color:#ffb4b4}
  .requirements-panel>.hint{margin:0;font-size:12px;flex-shrink:0}
</style>
