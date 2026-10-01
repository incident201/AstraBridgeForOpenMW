<script lang="ts">
  import {onMount} from 'svelte';
  import {Viewer,artifact,pointer} from './viewer';
  const pages=[['play','Play'],['atlas','Atlas'],['recordings','Recordings'],['settings','Settings'],['diagnostics','Diagnostics'],['setup','Setup']];
  let page='play',state:any={installed:false},runtime:any={},busy=false,error='',notice='',progress='';
  let game='',storage='',recordingsDirectory='',encoding='win1251',dataRelative='Data Files',development=false;
  let gameMode:'mount'|'copy'='mount';
  let setupStep='game',settingsSection='data',diagnosticSection='logs';
  let video:HTMLVideoElement,viewer=new Viewer(),watching=false,quality='720p30',muted=false;
  let gpus:any[]=[];
  let configuration:any=null,content='',archives='',recordings:any[]=[],selectedRecording:any=null,metadata:any=null;
  let atlas:any={},space='',selectedNode:any=null,logName='daemon.log',logs:any={names:[],text:''},environment:any={},history:any[]=[];
  $: owner=runtime.owner?.mode??'idle';
  $: manual=owner==='manual';
  $: if(owner!=='manual'&&typeof document!=='undefined'&&document.pointerLockElement)void document.exitPointerLock();

  async function refresh(){
    try{state=await window.astra.invoke('status');if(state.runtime)runtime=state.runtime;else runtime={};}
    catch(e){error=(e as Error).message;}
  }
  async function task(action:()=>Promise<any>,message=''){
    busy=true;error='';notice='';
    try{const result=await action();notice=message;await refresh();return result;}
    catch(e){error=(e as Error).message;}
    finally{busy=false;}
  }
  async function navigate(next:string){
    if(page==='play'&&next!=='play')await endWatch();
    page=next;error='';
    if(next==='recordings')await loadRecordings();
    if(next==='atlas')await loadAtlas();
    if(next==='settings')await task(async()=>{configuration=await window.astra.invoke('configuration');gpus=await window.astra.invoke('gpus');content=configuration.content.join('\n');archives=configuration.archives.join('\n');});
    if(next==='diagnostics')await loadDiagnostics();
  }
  async function choose(field:'game'|'storage'|'recordings'){const selected=await window.astra.invoke('choose-directory');if(selected){if(field==='game')game=selected;else if(field==='storage')storage=selected;else recordingsDirectory=selected;}}
  async function install(){
    progress='';await task(async()=>{await window.astra.invoke('install',{game,storage,encoding,dataRelative,development,gameMode,recordings:recordingsDirectory||undefined});page='play';},'Installation ready. Start the game when you are ready.');
  }
  async function watch(){await task(async()=>{await viewer.start(video,quality);watching=true;});}
  async function endWatch(){releaseInput();await viewer.close();watching=false;}
  async function changeQuality(){if(watching)await watch();}
  function releaseInput(){if(manual)window.astra.input({type:'manual.release'});if(document.pointerLockElement)void document.exitPointerLock();}
  function input(event:any){if(manual)window.astra.input({type:'input',event});}
  function mousemove(event:MouseEvent){
    if(!manual)return;
    if(document.pointerLockElement===video)input({type:'relative',x:event.movementX,y:event.movementY});
    else {const value=pointer(video,event);if(value)input(value);}
  }
  function mousebutton(event:MouseEvent,down:boolean){if(!manual)return;event.preventDefault();video.focus();const p=pointer(video,event);if(p)input(p);input({type:'button',button:event.button,down});}
  function key(event:KeyboardEvent,down:boolean){if(!manual||event.repeat)return;event.preventDefault();input({type:'key',code:event.code,down});}
  function wheel(event:WheelEvent){if(!manual)return;event.preventDefault();input({type:'wheel',steps:event.deltaY<0?1:-1});}
  async function loadRecordings(){await task(async()=>{recordings=await window.astra.invoke('recordings');});}
  async function selectRecording(row:any){selectedRecording=row;metadata=null;if(row.metadata)await task(async()=>{metadata=await window.astra.invoke('artifact-json',{path:row.metadata});});}
  async function loadAtlas(){await task(async()=>{atlas=await window.astra.invoke('atlas',space?{space}:{});selectedNode=null;});}
  async function loadDiagnostics(){await task(async()=>{logs=await window.astra.invoke('logs',{name:logName});
    if(state.container?.running){environment=await window.astra.invoke('environment');history=await window.astra.invoke('sessions');}});}
  const formatBytes=(n:number)=>n>1024**3?(n/1024**3).toFixed(2)+' GB':(n/1024**2).toFixed(1)+' MB';

  onMount(()=>{
    void refresh();const timer=setInterval(()=>void refresh(),2500);
    const unsubscribe=window.astra.subscribe(message=>{
      if(message.type==='status')runtime=message.data;
      if(message.type==='input.owner')runtime={...runtime,owner:message.data};
      if(message.type==='error')error=message.error;
      if(message.type==='progress')progress=(progress+message.data).slice(-12000);
    });
    window.addEventListener('blur',releaseInput);
    return()=>{clearInterval(timer);unsubscribe();releaseInput();void viewer.close();window.removeEventListener('blur',releaseInput);};
  });
</script>

<svelte:head><title>AstraBridge</title></svelte:head>
<div class="app-shell">
  <aside>
    <div class="brand"><span class="brand-mark">A</span><div>AstraBridge<small>OPENMW RUNTIME</small></div></div>
    <nav aria-label="Main navigation">
      {#each pages as [id,label]}<button class:active={page===id} on:click={()=>navigate(id)}>{label}</button>{/each}
    </nav>
    <div class="sidebar-footer"><span class:online={state.container?.running} class="dot"></span>{state.container?.running?'Runtime running':state.installed?'Runtime stopped':'Not installed'}
      <small>{state.release?.version??''} · {state.backend??'Linux / Windows'}</small>
    </div>
  </aside>
  <main class:play-page={page==='play'}>
    <header><div><p class="eyebrow">ASTRABRIDGE</p><h1>{pages.find(([id])=>id===page)?.[1]}</h1></div>
      <div class="toolbar">
        {#if state.installed}
          <button disabled={busy||runtime.running} class="primary" on:click={()=>task(()=>window.astra.invoke('start'))}>Start game</button>
          <button disabled={busy||!state.container?.running} on:click={()=>task(async()=>{await endWatch();return window.astra.invoke('stop');})}>Stop runtime</button>
          <button disabled={busy} on:click={()=>task(async()=>{await endWatch();return window.astra.invoke('restart');})}>Restart</button>
        {/if}
      </div>
    </header>
    {#if error}<div role="alert" class="banner error">{error}<button on:click={()=>error=''} aria-label="Dismiss error">×</button></div>{/if}
    {#if notice}<div role="status" class="banner">{notice}</div>{/if}
    {#if busy}<div class="working" role="status">Working…</div>{/if}
    {#if !state.installed&&page!=='setup'}<section class="empty"><h2>Set up your game</h2><p>Import your Morrowind installation and install the AstraBridge runtime.</p><button class="primary" on:click={()=>navigate('setup')}>Open setup</button></section>{/if}

    {#if page==='play'&&state.installed}
      <div class="status-grid">
        <div class="metric"><small>CONTROL</small><strong>{owner==='agent'?'Agent connected':manual?'Manual control':'Paused / idle'}</strong><span>{runtime.owner?.name??'No active controller'}</span></div>
        <div class="metric"><small>ACTIVE ACTION</small><strong>{runtime.active_action?.operation??'None'}</strong><span>{runtime.active_action?.phase??'Ready'}</span></div>
        <div class="metric"><small>RECORDING</small><strong>{runtime.recording?'Recording':'Off'}</strong><span>{runtime.recording?.encoder??'1080p · 60 fps'}</span></div>
        <div class="metric"><small>GRAPHICS</small><strong>{runtime.graphics?.hardware_accelerated?'GPU accelerated':'Not started'}</strong><span>{runtime.graphics?.renderer??'Private display'}</span></div>
      </div>
      <section class="viewer-panel">
        <div class="section-heading"><h2>Live view</h2><div class="toolbar">
          <select aria-label="Viewer quality" bind:value={quality} on:change={changeQuality} disabled={busy}><option>720p30</option><option>1080p60</option></select>
          {#if watching}<button on:click={endWatch}>Disconnect viewer</button>{:else}<button disabled={!runtime.running||busy} on:click={watch}>Open viewer</button>{/if}
          <button disabled={!watching} on:click={()=>{muted=!muted;video.muted=muted;}}>{muted?'Unmute':'Mute'}</button>
        </div></div>
        <div class="video-wrap">
          <!-- The video is an intentional keyboard/mouse game surface. -->
          <!-- svelte-ignore a11y_media_has_caption a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
          <video bind:this={video} autoplay playsinline tabindex="0" aria-label="Live Morrowind game"
            on:mousemove={mousemove} on:mousedown={e=>mousebutton(e,true)} on:mouseup={e=>mousebutton(e,false)}
            on:keydown={e=>key(e,true)} on:keyup={e=>key(e,false)} on:wheel|nonpassive={wheel} on:contextmenu|preventDefault={()=>{}}></video>
          {#if !watching}<div class="video-placeholder"><span>A</span><p>{runtime.running?'Open the viewer to watch your game.':'Start the game to open the live view.'}</p></div>{/if}
        </div>
        <div class="viewer-controls"><div class="toolbar">
          {#if manual}<button on:click={releaseInput}>Release control</button><button on:click={()=>video.requestPointerLock()}>Lock pointer for camera</button>
          {:else}<button disabled={!watching||owner==='agent'} on:click={()=>window.astra.input({type:'manual.acquire'})}>{owner==='agent'?'Agent owns input':'Take manual control'}</button>{/if}
          <span class="hint">Escape releases pointer lock. Leaving the window releases manual control.</span>
        </div><span class="hint">Viewer quality does not change recording quality.</span></div>
      </section>
      <div class="toolbar bottom-actions">
        <button disabled={!runtime.running||busy} on:click={()=>task(()=>window.astra.invoke('record',{action:runtime.recording?'stop':'start'}))}>{runtime.recording?'Stop recording':'Start recording'}</button>
        <button on:click={()=>task(()=>window.astra.invoke('skill-export'),'Skill exported. Give the exported folder to your agent.')}>Export gameplay skill</button>
        {#if owner==='agent'}<button class="danger" on:click={()=>task(()=>window.astra.invoke('agent-end'),'Agent session ended. Manual control is now available.')}>End agent session</button>{/if}
      </div>
    {:else if page==='setup'}
      <section class="card setup-card"><h2>{state.installed?'Your installation':'Install AstraBridge runtime'}</h2>
        {#if state.installed}
          <p>The managed installation is ready at <code>{state.storageDirectory}</code>.</p>
          <div class="toolbar"><button on:click={()=>task(()=>window.astra.invoke('skill-export'),'Skill exported.')}>Export gameplay skill</button></div>
          <h3>Runtime version</h3><p>Desktop {state.release?.version}. Updates are explicit and preserve your managed game and state.</p><p class="hint">{state.currentDigest}</p>
          <div class="toolbar"><button disabled={busy||!state.updateRequired} on:click={()=>task(()=>window.astra.invoke('update'),'Runtime updated.')}>{state.updateRequired?'Update runtime':'Runtime matches Desktop'}</button></div>
        {:else}
          <div class="tabs" aria-label="Setup steps"><button class:active={setupStep==='game'} on:click={()=>setupStep='game'}>1. Game</button><button class:active={setupStep==='storage'} on:click={()=>setupStep='storage'}>2. Storage</button></div>
          <div class="setup-fields">
          {#if setupStep==='game'}
            <label>Morrowind installation<div class="field-row"><input bind:value={game} placeholder="Choose your existing Morrowind folder"><button on:click={()=>choose('game')}>Browse</button></div></label>
            <label>Game data source<select bind:value={gameMode}><option value="mount">Use the host folder — no copying (default)</option><option value="copy">Copy into managed storage</option></select></label>
            <p class="hint">{gameMode==='mount'?'Host edits are visible to the runtime. Stop the game before editing the source folder.':'The managed copy is independent of later changes to the original folder.'}</p>
            <div class="form-grid"><label>Data directory inside the game folder<input bind:value={dataRelative} placeholder="Data Files"></label>
            <label>Game text encoding<select bind:value={encoding}><option value="win1251">Windows-1251 (Cyrillic)</option><option value="win1252">Windows-1252 (Western European)</option><option value="win1250">Windows-1250 (Central European)</option></select></label></div>
            <p class="hint">Active plugins and archives are read from Morrowind.ini. If no INI is present, configure the content list in Settings before starting.</p>
          {:else}
            <label>Managed storage<div class="field-row"><input bind:value={storage} placeholder="Choose a storage location"><button on:click={()=>choose('storage')}>Browse</button></div></label>
            <label>Recordings folder on this computer<div class="field-row"><input bind:value={recordingsDirectory} placeholder="Defaults to recordings inside managed storage"><button on:click={()=>choose('recordings')}>Browse</button></div></label>
            <label class="checkbox"><input type="checkbox" bind:checked={development}>Development mode (console and runtime overrides)</label>
            {#if progress}<pre class="setup-progress">{progress}</pre>{/if}
          {/if}
          </div>
          <div class="card-footer toolbar">
            {#if setupStep==='game'}<button class="primary" disabled={!game||busy} on:click={()=>setupStep='storage'}>Next: Storage</button>
            {:else}<button disabled={!storage||busy} on:click={()=>task(async()=>{const result=await window.astra.invoke('prerequisites',{storage});if(!result.available)throw new Error(result.message);return result;},'Container runtime is available.')}>Check prerequisites</button><button class="primary" disabled={!game||!storage||busy} on:click={install}>Install</button>{/if}
          </div>
        {/if}
      </section>
    {:else if page==='atlas'&&state.installed}
      <section class="card atlas-card"><div class="section-heading"><div><h2>Travelled world</h2><p>Places and routes learned during this installation.</p></div><div class="toolbar"><select aria-label="Atlas location" bind:value={space} on:change={loadAtlas}><option value="">Current location</option>{#each atlas.spaces??[] as location}<option value={location.ref}>{location.location??location.label??location.ref}</option>{/each}</select><button on:click={loadAtlas}>Refresh</button></div></div>
        {#if atlas.supported}<div class="atlas-grid"><div class="map-pane">{#if atlas.svg}<img class="atlas-image" src={artifact(atlas.svg)} alt="Map of travelled routes">{/if}<p>{atlas.location} · {atlas.recorded_points??0} recorded points</p></div>
        <div class="scroll-region"><h3>Visited points</h3>{#each atlas.nodes??[] as node}<button class="node-row" class:selected={selectedNode?.ref===node.ref} on:click={()=>selectedNode=node}><strong>{node.label}</strong><span>{node.distance_m} m · {node.visits} visits</span></button>{/each}</div></div>
        {#if selectedNode}<section class="details"><h3>{selectedNode.label}</h3><p>{selectedNode.location}</p><p>{selectedNode.names?.join(', ')}</p><p>Route distance: {selectedNode.route_distance_m??'Unknown'} m · {selectedNode.can_revisit?'Route available':'No current route'}</p>{#each selectedNode.landmarks??[] as landmark}<p>{typeof landmark==='string'?landmark:landmark.name??landmark.label??landmark.kind}</p>{/each}</section>{/if}
        {#if atlas.transitions?.length}<h3>Transitions</h3><pre>{JSON.stringify(atlas.transitions,null,2)}</pre>{/if}
        {:else}<div class="empty"><p>No travelled map yet. Explore the game to build the Atlas.</p></div>{/if}
      </section>
    {:else if page==='recordings'&&state.installed}
      <section class="card recordings-card"><div class="section-heading"><h2>Recordings</h2><div class="toolbar"><button disabled={!runtime.running||busy} on:click={()=>task(()=>window.astra.invoke('record',{action:runtime.recording?'stop':'start'}))}>{runtime.recording?'Stop recording':'Start recording'}</button><button on:click={()=>task(()=>window.astra.invoke('open-recordings-folder'))}>Open folder</button><button on:click={loadRecordings}>Refresh</button></div></div>
        <p class="hint">{state.recordingsDirectory}</p>
        <div class="recording-grid"><div class="scroll-region">{#each recordings as row}<button class="node-row" class:selected={selectedRecording?.id===row.id} on:click={()=>selectRecording(row)}><strong>{row.name}</strong><span>{new Date(row.created*1000).toLocaleString()} · {formatBytes(row.bytes)}</span></button>{:else}<p>No recordings yet.</p>{/each}</div>
        <div class="recording-preview">{#if selectedRecording}<!-- svelte-ignore a11y_media_has_caption --><video class="playback" src={artifact(selectedRecording.video)} controls></video><div class="toolbar"><button on:click={()=>task(()=>window.astra.invoke('export-artifact',{path:selectedRecording.video,name:selectedRecording.name}),'Recording exported.')}>Export MP4</button>{#if selectedRecording.metadata}<button on:click={()=>task(()=>window.astra.invoke('export-artifact',{path:selectedRecording.metadata,name:selectedRecording.name+'.json'}),'Metadata exported.')}>Export metadata</button>{/if}</div>{#if metadata}<details><summary>Recording metadata</summary><pre>{JSON.stringify(metadata,null,2)}</pre></details>{/if}{:else}<div class="empty"><p>Select a recording to play or export it.</p></div>{/if}</div></div>
      </section>
    {:else if page==='settings'&&configuration}
      <section class="card settings-card"><div class="section-heading"><h2>Configuration</h2>{#if runtime.running}<button on:click={()=>task(()=>window.astra.invoke('stop-game'))}>Stop game to edit</button>{/if}</div>
        <div class="tabs" aria-label="Configuration sections">{#each [['data','Game data'],['gameplay','Gameplay'],['graphics','Graphics and recording']] as [id,label]}<button class:active={settingsSection===id} aria-pressed={settingsSection===id} on:click={()=>settingsSection=id}>{label}</button>{/each}</div>
        <p class="hint">Changes apply on the next game start.</p>
        <fieldset class="settings-fields" disabled={runtime.running||busy}>
          {#if settingsSection==='data'}
            <div class="form-grid">
              <label>Data directory<input bind:value={configuration.data_relative}></label>
              <label>Encoding<select bind:value={configuration.encoding}><option value="win1251">Windows-1251</option><option value="win1252">Windows-1252</option><option value="win1250">Windows-1250</option></select></label>
              <label>Active content, in load order<textarea rows="6" bind:value={content}></textarea></label>
              <label>Archives<textarea rows="6" bind:value={archives}></textarea></label>
            </div>
            <p class="hint">Original game files are read-only. List plugins in their intended load order.</p>
          {:else if settingsSection==='gameplay'}
            <label>Difficulty<input type="number" min="-500" max="500" bind:value={configuration.difficulty}></label>
            <label class="checkbox"><input type="checkbox" bind:checked={configuration.best_attack}>Always use best attack</label>
            <p class="hint">Difficulty −100 and best attack were chosen for testing convenience. You can change both.</p>
            <label class="checkbox"><input type="checkbox" bind:checked={configuration.delay_tribunal}>Delay Dark Brotherhood attacks until the main quest completion gate</label>
            <label class="checkbox"><input type="checkbox" bind:checked={configuration.sound}>Game sound</label>
          {:else}
            <label>Game GPU<select aria-label="Game GPU" bind:value={configuration.graphics_gpu}><option value="auto">Automatic / default GPU</option>{#each gpus as gpu}<option value={gpu.id} disabled={!gpu.render_selectable||!gpu.accessible}>{gpu.name} · {gpu.pci}{!gpu.render_selectable?' (exact rendering selection unavailable)':''}</option>{/each}</select></label>
            <div class="form-grid">
              <label>Encoder<select bind:value={configuration.recording_encoder}><option value="auto">Automatic (GPU preferred)</option><option value="cpu">CPU — libx264</option><option value="vaapi">VAAPI</option><option value="nvenc">NVIDIA NVENC</option></select></label>
              <label>Encoding GPU<select aria-label="Encoding GPU" bind:value={configuration.encoding_gpu} disabled={configuration.recording_encoder==='cpu'} on:change={()=>configuration.vaapi_device=null}><option value="auto">Automatic (probe available devices)</option>{#each gpus as gpu}<option value={gpu.id} disabled={!gpu.accessible}>{gpu.name} · {gpu.pci}</option>{/each}</select></label>
            </div>
            <p class="hint">Rendering and encoding can use different GPUs. Recording and live view use the encoding choice. Automatic encoder mode allows CPU fallback; explicit VAAPI or NVENC reports an error if unavailable.</p>
            {#if configuration.graphics_gpu!=='auto'&&!gpus.some(gpu=>gpu.id===configuration.graphics_gpu)}<p class="hint">Saved rendering device: {configuration.graphics_gpu}. It may be unavailable.</p>{/if}
            {#if configuration.encoding_gpu!=='auto'&&!gpus.some(gpu=>gpu.id===configuration.encoding_gpu)}<p class="hint">Saved encoding device: {configuration.encoding_gpu}. It may be unavailable.</p>{/if}
            <label>VAAPI device override (optional)<input disabled={configuration.encoding_gpu!=='auto'} value={configuration.vaapi_device??''} on:input={event=>configuration.vaapi_device=event.currentTarget.value||null} placeholder="Automatic"></label>
          {/if}
        </fieldset>
        <div class="card-footer"><button class="primary" disabled={runtime.running||busy} on:click={()=>task(async()=>{configuration=await window.astra.invoke('configure',{...configuration,content:content.split('\n').map(x=>x.trim()).filter(Boolean),archives:archives.split('\n').map(x=>x.trim()).filter(Boolean)});},'Configuration saved.')}>Save configuration</button></div>
      </section>
    {:else if page==='diagnostics'&&state.installed}
      <section class="card diagnostics-card"><div class="section-heading"><h2>Runtime diagnostics</h2><button on:click={loadDiagnostics}>Refresh</button></div>
        <div class="status-grid"><div class="metric"><small>CAPTURE</small><strong>{Math.max(0,runtime.capture_fps??0).toFixed(1)} fps</strong></div><div class="metric"><small>VIEWER</small><strong>{runtime.viewer?.quality??'Off'}</strong></div><div class="metric"><small>ENCODER</small><strong>{runtime.viewer?.encoder?.encoder??'Not active'}</strong></div><div class="metric"><small>LIVE AUDIO GAPS</small><strong>{runtime.viewer?.audio_discontinuities??0}</strong></div></div>
        <div class="section-heading"><div class="tabs" aria-label="Diagnostic sections">{#each [['logs','Logs'],['environment','Environment'],['sessions','Sessions']] as [id,label]}<button class:active={diagnosticSection===id} aria-pressed={diagnosticSection===id} on:click={()=>diagnosticSection=id}>{label}</button>{/each}</div>
        {#if diagnosticSection==='logs'}<select aria-label="Diagnostic log" bind:value={logName} on:change={loadDiagnostics}>{#each logs.names?.length?logs.names:['daemon.log'] as name}<option>{name}</option>{/each}</select>{/if}</div>
        <pre class="log">{diagnosticSection==='logs'?logs.text||'No log output yet.':JSON.stringify(diagnosticSection==='environment'?environment:history,null,2)}</pre>
      </section>
    {/if}
  </main>
</div>
