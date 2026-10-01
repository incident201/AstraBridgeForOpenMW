<script lang="ts">
  import {onMount} from 'svelte';
  import Icon from './Icon.svelte';
  import {ReplayViewer,type ReplayInfo} from './replay';
  import {Viewer,artifact,pointer} from './viewer';
  const pages=[['play','Play'],['atlas','Atlas'],['recordings','Recordings'],['profiles','Profiles'],['settings','Settings'],['diagnostics','Diagnostics'],['setup','Setup']];
  let page='play',state:any={installed:false},runtime:any={},busy=false,error='',notice='',progress='';
  let game='',storage='',recordingsDirectory='',encoding='win1251',dataRelative='Data Files',development=false;
  let gameMode:'mount'|'copy'='mount';
  let setupStep='game',installedSection='runtime',settingsSection='data',diagnosticSection='logs';
  let video:HTMLVideoElement,viewer=new Viewer(),watching=false,quality='720p30',muted=false;
  let fullscreen=false,fullscreenControls=true,fullscreenTimer:ReturnType<typeof setTimeout>;
  let replayVideo:HTMLVideoElement,replay:ReplayViewer|null=null,viewMode:'live'|'replay'|'still'='live';
  let replayInfo:ReplayInfo={id:null,ready:false,active:false,duration:0},replayPosition=0,replayPlaying=false,replayBusy=false,replayError='';
  let seekDraft=0,seeking=false,seekSerial=0,pollingReplay=false;
  let gpus:any[]=[];
  let configuration:any=null,content='',archives='',recordings:any[]=[],selectedRecording:any=null,metadata:any=null;
  let atlas:any={},space='',selectedNode:any=null,logName='daemon.log',logs:any={names:[],text:''},environment:any={},history:any[]=[];
  let profiles:any[]=[],selectedProfile:any=null,profileForm='',profileName='',lastProfile='';
  $: owner=runtime.owner?.mode??'idle';
  $: manual=owner==='manual';
  $: if(runtime.profile?.id&&runtime.profile.id!==lastProfile){
    lastProfile=runtime.profile.id;atlas={};space='';selectedNode=null;recordings=[];selectedRecording=null;metadata=null;history=[];logs={names:[],text:''};configuration=null;
    replayInfo={id:null,ready:false,active:false,duration:0};replay?.close();replay=null;viewMode='live';
  }
  $: if(owner!=='manual'&&typeof document!=='undefined'&&document.pointerLockElement)void document.exitPointerLock();

  async function refresh(){
    try{state=await window.astra.invoke('status');if(state.runtime)runtime=state.runtime;else runtime={};}
    catch(e){error=(e as Error).message;}
  }
  async function task(action:()=>Promise<any>,message=''){
    busy=true;error='';notice='';
    try{const result=await action();if(message)notice=message;await refresh();return result;}
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
    if(next==='profiles')await loadProfiles();
  }
  async function loadProfiles(){await task(async()=>{const data=await window.astra.invoke('profiles');profiles=data.profiles;selectedProfile=profiles.find(p=>p.id===selectedProfile?.id)??profiles.find(p=>p.active);profileForm='';});}
  function profileEdit(operation:string){profileForm=operation;profileName=operation==='rename'?selectedProfile.name:operation==='duplicate'?selectedProfile.name+' copy':'';}
  async function changeProfile(operation:string){await task(async()=>{
    const data=await window.astra.invoke('profile',{operation,...(operation==='create'?{}:{id:selectedProfile.id}),...(['create','rename','duplicate'].includes(operation)?{name:profileName}:{})});
    profiles=data.profiles;selectedProfile=profiles.find(p=>p.id===(data.result?.id??selectedProfile?.id))??profiles.find(p=>p.active);profileForm='';
    if(!data.cancelled)notice=operation==='duplicate'?'Independent profile copy created.':operation==='delete'?'Profile deleted. Video recordings are kept on your computer.':'';
  });}
  async function choose(field:'game'|'storage'|'recordings'){const selected=await window.astra.invoke('choose-directory');if(selected){if(field==='game')game=selected;else if(field==='storage')storage=selected;else recordingsDirectory=selected;}}
  async function install(){
    progress='';await task(async()=>{await window.astra.invoke('install',{game,storage,encoding,dataRelative,development,gameMode,recordings:recordingsDirectory||undefined});page='play';},'Installation ready. Start the game when you are ready.');
  }
  async function watch(){await task(async()=>{await viewer.start(video,quality);watching=true;video.muted=muted||viewMode!=='live';});}
  async function endWatch(){
    seekSerial++;replay?.close();replay=null;viewMode='live';await window.astra.invoke('viewer-review',{enabled:false});
    releaseInput();if(fullscreen){await window.astra.invoke('viewer-fullscreen',{enabled:false});setViewerFullscreen(false);}
    await viewer.close();watching=false;
  }
  async function pollReplay(){
    if(pollingReplay||page!=='play'||!state.container?.running||viewMode==='replay')return;
    pollingReplay=true;
    const mode=viewMode,serial=seekSerial;
    try{const info=await window.astra.invoke('replay-info',mode==='still'?{id:replayInfo.id}:{});
      if(page==='play'&&viewMode===mode&&seekSerial===serial)replayInfo=info;}
    catch{if(viewMode==='live')replayInfo={id:null,ready:false,active:false,duration:0};}
    finally{pollingReplay=false;}
  }
  async function reviewMode(mode:'replay'|'still'){
    if(manual)window.astra.input({type:'input',event:{type:'release'}});
    if(document.pointerLockElement)void document.exitPointerLock();
    viewMode=mode;video.muted=true;
    await window.astra.invoke('viewer-review',{enabled:true});
  }
  async function seekReplay(position:number,play=false){
    const serial=++seekSerial;replayBusy=true;replayError='';
    try{
      await reviewMode('replay');
      const info:ReplayInfo=await window.astra.invoke('replay-info',{id:replayInfo.id});
      if(serial!==seekSerial)return;
      replayInfo=info;replayPosition=position;
      replay??=new ReplayViewer(replayVideo,value=>replayInfo=value,message=>replayError=message);
      replayVideo.muted=muted;
      try{await replay.seek(info,position,play);}
      catch(original){
        if(serial!==seekSerial)return;
        const updated:ReplayInfo=await window.astra.invoke('replay-info',{id:info.id});
        if(updated.ready&&updated.generation!==info.generation){replayInfo=updated;await replay.seek(updated,position,play);}
        else throw original;
      }
    }catch(e){if(serial===seekSerial&&(e as Error).name!=='AbortError')replayError=(e as Error).message;}
    finally{if(serial===seekSerial){replayBusy=false;seeking=false;}}
  }
  async function goLive(){
    seekSerial++;replay?.close();replay=null;viewMode='live';replayError='';replayBusy=false;seeking=false;
    await window.astra.invoke('viewer-review',{enabled:false});
    if(!watching)await watch();else {video.muted=muted;await video.play();}
    await pollReplay();video.focus();
  }
  async function togglePlayback(){
    try{
      if(viewMode==='replay'){
        if(replayVideo.paused)await replay?.play();else replay?.pause();
      }else if(viewMode==='still'){
        if(replayInfo.ready)await seekReplay(replayPosition,true);else await goLive();
      }else if(replayInfo.ready)await seekReplay(replayInfo.duration,false);
      else {replayPosition=runtime.recording?.duration??0;await reviewMode('still');video.pause();}
    }catch(e){replayError=(e as Error).message;}
  }
  function replayTime(){if(viewMode==='replay'&&replay)replayPosition=replay.position;}
  function changeMute(){muted=!muted;video.muted=muted||viewMode!=='live';if(replayVideo)replayVideo.muted=muted;}
  function formatTime(value:number){
    const seconds=Math.max(0,Number.isFinite(value)?value:0),minutes=Math.floor(seconds/60);
    return (minutes>=60?Math.floor(minutes/60)+':'+String(minutes%60).padStart(2,'0'):String(minutes))+':'+String(Math.floor(seconds%60)).padStart(2,'0');
  }
  function revealFullscreenControls(){
    if(!fullscreen||document.pointerLockElement===video)return;
    fullscreenControls=true;clearTimeout(fullscreenTimer);
    fullscreenTimer=setTimeout(()=>fullscreenControls=false,2200);
  }
  function setViewerFullscreen(enabled:boolean){
    fullscreen=enabled;
    clearTimeout(fullscreenTimer);fullscreenControls=true;
    if(fullscreen)revealFullscreenControls();
  }
  async function toggleFullscreen(){
    try{input({type:'release'});const result=await window.astra.invoke('viewer-fullscreen',{enabled:!fullscreen});setViewerFullscreen(result.enabled);video.focus();}
    catch(e){error=(e as Error).message;}
  }
  async function changeQuality(){if(watching)await watch();}
  function releaseInput(){if(manual)window.astra.input({type:'manual.release'});if(document.pointerLockElement)void document.exitPointerLock();}
  function input(event:any){if(manual&&viewMode==='live')window.astra.input({type:'input',event});}
  function mousemove(event:MouseEvent){
    if(!manual||viewMode!=='live')return;
    if(document.pointerLockElement===video)input({type:'relative',x:event.movementX,y:event.movementY});
    else {const value=pointer(video,event);if(value)input(value);}
  }
  function mousebutton(event:MouseEvent,down:boolean){if(!manual||viewMode!=='live')return;event.preventDefault();video.focus();const p=pointer(video,event);if(p)input(p);input({type:'button',button:event.button,down});}
  function key(event:KeyboardEvent,down:boolean){if(!manual||viewMode!=='live'||event.repeat)return;event.preventDefault();input({type:'key',code:event.code,down});}
  function wheel(event:WheelEvent){if(!manual||viewMode!=='live')return;event.preventDefault();input({type:'wheel',steps:event.deltaY<0?1:-1});}
  async function loadRecordings(){await task(async()=>{recordings=await window.astra.invoke('recordings');});}
  async function selectRecording(row:any){selectedRecording=row;metadata=null;if(row.metadata)await task(async()=>{metadata=await window.astra.invoke('artifact-json',{path:row.metadata});});}
  async function loadAtlas(){await task(async()=>{atlas=await window.astra.invoke('atlas',space?{space}:{});selectedNode=null;});}
  async function loadDiagnostics(){await task(async()=>{logs=await window.astra.invoke('logs',{name:logName});
    if(state.container?.running){environment=await window.astra.invoke('environment');history=await window.astra.invoke('sessions');}});}
  const formatBytes=(n:number)=>n>1024**3?(n/1024**3).toFixed(2)+' GB':(n/1024**2).toFixed(1)+' MB';

  onMount(()=>{
    void refresh();const timer=setInterval(()=>void refresh(),2500);
    const replayTimer=setInterval(()=>void pollReplay(),1000);
    const unsubscribe=window.astra.subscribe(message=>{
      if(message.type==='viewer.fullscreen')setViewerFullscreen(message.enabled);
      if(message.type==='status')runtime=message.data;
      if(message.type==='input.owner')runtime={...runtime,owner:message.data};
      if(message.type==='error')error=message.error;
      if(message.type==='progress')progress=(progress+message.data).slice(-12000);
    });
    const pointerLockChanged=()=>{if(!document.pointerLockElement)revealFullscreenControls();};
    document.addEventListener('mousemove',revealFullscreenControls);
    document.addEventListener('pointerlockchange',pointerLockChanged);
    window.addEventListener('blur',releaseInput);
    return()=>{clearInterval(timer);clearInterval(replayTimer);replay?.close();clearTimeout(fullscreenTimer);unsubscribe();releaseInput();void viewer.close();
      document.removeEventListener('mousemove',revealFullscreenControls);document.removeEventListener('pointerlockchange',pointerLockChanged);window.removeEventListener('blur',releaseInput);};
  });
</script>

<svelte:head><title>AstraBridge</title></svelte:head>
<div class="app-shell">
  <aside inert={fullscreen}>
    <div class="brand"><span class="brand-mark">A</span><div>AstraBridge<small>OPENMW<br>RUNTIME</small></div></div>
    <nav aria-label="Main navigation">
      {#each pages as [id,label]}<button class:active={page===id} on:click={()=>navigate(id)}><Icon name={id}/><span>{label}</span></button>{/each}
    </nav>
    <div class="sidebar-footer"><span class:online={state.container?.running} class="dot"></span>{state.container?.running?'Runtime running':state.installed?'Runtime stopped':'Not installed'}
      {#if runtime.profile}<small class="active-profile" title={runtime.profile.name}>Profile · {runtime.profile.name}</small>{/if}
      <small>{state.release?.version??''} · {state.backend??'Linux / Windows'}</small>
    </div>
  </aside>
  <main class:play-page={page==='play'}>
    <header inert={fullscreen}><div><p class="eyebrow">ASTRABRIDGE</p><h1>{pages.find(([id])=>id===page)?.[1]}</h1></div>
      <div class="toolbar">
        {#if state.installed}
          <button disabled={busy||runtime.running||!state.container?.exists} class="primary" on:click={()=>task(()=>window.astra.invoke('start'))}><Icon name="play" size={19}/>Start game</button>
          <button disabled={busy||!state.container?.running} on:click={()=>task(async()=>{await endWatch();return window.astra.invoke('stop');})}><Icon name="stop" size={17}/>Stop runtime</button>
          <button disabled={busy} on:click={()=>task(async()=>{await endWatch();return window.astra.invoke('restart');})}><Icon name="restart" size={20}/>Restart</button>
        {/if}
      </div>
    </header>
    {#if state.installed&&(state.updatePending||state.updateRequired)&&page!=='setup'}<div class="banner" role="status"><span>{state.updatePending?'A runtime update was interrupted. Open Setup to recover your previous runtime.':'This Desktop needs its matching runtime. Open Setup to update; your saved data will be kept.'}</span><button on:click={()=>navigate('setup')}>Open setup</button></div>{/if}
    {#if error}<div role="alert" class="banner error">{error}<button on:click={()=>error=''} aria-label="Dismiss error">×</button></div>{/if}
    {#if notice}<div role="status" class="banner">{notice}</div>{/if}
    {#if busy}<div class="working" role="status">Working…</div>{/if}
    {#if !state.installed&&page!=='setup'}<section class="empty"><h2>Set up your game</h2><p>Import your Morrowind installation and install the AstraBridge runtime.</p><button class="primary" on:click={()=>navigate('setup')}>Open setup</button></section>{/if}

    {#if page==='play'&&state.installed}
      <div class="status-grid" inert={fullscreen}>
        <div class="metric"><div class="metric-icon"><Icon name="control" size={26}/></div><div class="metric-copy"><small>CONTROL</small><strong>{owner==='agent'?'Agent connected':manual?'Manual control':'Paused / idle'}</strong><span>{runtime.owner?.name??'No active controller'}</span></div></div>
        <div class="metric"><div class="metric-icon"><Icon name="cursor" size={25}/></div><div class="metric-copy"><small>ACTIVE ACTION</small><strong>{runtime.active_action?.operation??'None'}</strong><span>{runtime.active_action?.phase??'Ready'}</span></div></div>
        <div class="metric" class:recording={Boolean(runtime.recording)}><div class="metric-icon"><Icon name="record" size={24}/></div><div class="metric-copy"><small>RECORDING</small><strong>{runtime.recording?'Recording':'Off'}</strong><span>{runtime.recording?.encoder??'1080p · 60 fps'}</span></div></div>
        <div class="metric"><div class="metric-icon accent"><Icon name="monitor" size={26}/></div><div class="metric-copy"><small>GRAPHICS</small><strong>{runtime.graphics?.hardware_accelerated?'GPU accelerated':'Not started'}</strong><span>{runtime.graphics?.renderer??'Private display'}</span></div></div>
      </div>
      <section class="viewer-panel" class:fullscreen-controls={fullscreenControls} class:viewer-fullscreen={fullscreen} aria-labelledby="live-view-title">
        <div class="section-heading"><h2 id="live-view-title"><Icon name="monitor" size={27}/>Live view</h2><div class="toolbar">
          <button disabled={!watching} on:click={toggleFullscreen} aria-pressed={fullscreen}><Icon name={fullscreen?'minimize':'fullscreen'} size={20}/>{fullscreen?'Exit fullscreen':'Fullscreen'}</button>
          <select aria-label="Viewer quality" bind:value={quality} on:change={changeQuality} disabled={busy}><option>720p30</option><option>1080p60</option></select>
          {#if watching}<button on:click={endWatch}><Icon name="disconnect" size={19}/>Disconnect viewer</button>{:else}<button disabled={!runtime.running||busy} on:click={watch}><Icon name="monitor" size={20}/>Open viewer</button>{/if}
          <button disabled={!watching} on:click={changeMute}><Icon name={muted?'mute':'volume'} size={19}/>{muted?'Unmute':'Mute'}</button>
        </div></div>
        <div class="video-wrap">
          <!-- The video is an intentional keyboard/mouse game surface. -->
          <!-- svelte-ignore a11y_media_has_caption a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
          <video class:concealed={viewMode==='replay'} bind:this={video} autoplay playsinline tabindex="0" aria-label="Live Morrowind game"
            on:mousemove={mousemove} on:mousedown={e=>mousebutton(e,true)} on:mouseup={e=>mousebutton(e,false)}
            on:keydown={e=>key(e,true)} on:keyup={e=>key(e,false)} on:wheel|nonpassive={wheel} on:contextmenu|preventDefault={()=>{}}></video>
          <!-- svelte-ignore a11y_media_has_caption -->
          <video class:concealed={viewMode!=='replay'} bind:this={replayVideo} playsinline aria-label="Recording replay"
            on:timeupdate={replayTime} on:seeked={replayTime} on:play={()=>replayPlaying=true} on:pause={()=>replayPlaying=false}></video>
          {#if viewMode!=='live'}<span class="replay-badge">{viewMode==='still'||!replayPlaying?'Paused view':'Replay'}</span>{/if}
          {#if replayBusy}<div class="replay-loading" role="status">Loading recording…</div>{/if}
          {#if replayError}<div class="replay-error" role="alert">{replayError}</div>{/if}
          {#if !watching&&viewMode==='live'}<div class="video-placeholder"><span>A</span><p>{runtime.running?'Open the viewer to watch your game.':'Start the game to open the live view.'}</p></div>{/if}
        </div>
        <div class="viewer-controls">
          <div class="timeline" aria-label="Viewer playback">
            <button class="playback-toggle" aria-label={viewMode==='live'||replayPlaying?'Pause playback':'Play playback'} title="Playback only; the game continues" disabled={replayBusy||(!watching&&!replayInfo.ready)} on:click={togglePlayback}><Icon name={viewMode==='live'||replayPlaying?'pause':'play'} size={19}/></button>
            <input class="timeline-range" aria-label="Recording timeline" type="range" min="0" max={Math.max(.001,replayInfo.duration)} step="0.01"
              disabled={!replayInfo.ready} value={seeking?seekDraft:viewMode==='live'?replayInfo.duration:Math.min(replayPosition,replayInfo.duration)}
              on:input={event=>{seeking=true;seekDraft=Number(event.currentTarget.value);}}
              on:change={()=>seekReplay(seekDraft,viewMode==='replay'&&replayPlaying)}>
            <span class="timeline-time">{replayInfo.ready?formatTime(seeking?seekDraft:viewMode==='live'?replayInfo.duration:replayPosition)+' / '+formatTime(replayInfo.duration):replayInfo.active?'Preparing recording…':'Recording is off'}</span>
            <button class="live-button" class:active={viewMode==='live'} aria-label="Return to live" disabled={!watching&&!runtime.running} on:click={()=>void goLive().catch(e=>replayError=e.message)}><span class="live-dot"></span>{viewMode==='live'?'Live':'Go live'}</button>
          </div>
          <div class="toolbar">
          {#if viewMode!=='live'}<span class="hint replay-notice">Viewing recorded footage. Game input is disabled; gameplay and recording continue.</span>
          {:else if manual}<button on:click={releaseInput}><Icon name="cursor" size={20}/>Release control</button><button on:click={()=>{video.focus();void video.requestPointerLock();}}><Icon name="lock" size={18}/>Lock pointer for camera</button>
          {:else}<button class="outline-accent" disabled={!watching||owner==='agent'} on:click={()=>window.astra.input({type:'manual.acquire'})}><Icon name="cursor" size={21}/>{owner==='agent'?'Agent owns input':'Take manual control'}</button>{/if}
          {#if viewMode==='live'}<span class="hint">Escape releases pointer lock. Leaving the window releases manual control.</span>{/if}
        </div><span class="hint">Viewer quality does not change recording quality.</span></div>
      </section>
      <div class="toolbar bottom-actions" inert={fullscreen}>
        <button disabled={!runtime.running||busy} on:click={()=>task(()=>window.astra.invoke('record',{action:runtime.recording?'stop':'start'}))}><Icon name="record" size={20}/>{runtime.recording?'Stop recording':'Start recording'}</button>
        <button on:click={()=>task(()=>window.astra.invoke('skill-export'),'Skill exported. Give the exported folder to your agent.')}><Icon name="export" size={20}/>Export gameplay skill</button>
        {#if owner==='agent'}<button class="danger" on:click={()=>task(()=>window.astra.invoke('agent-end'),'Agent session ended. Manual control is now available.')}>End agent session</button>{/if}
      </div>
    {:else if page==='setup'}
      <section class="card setup-card"><h2>{state.installed?'Your installation':'Install AstraBridge runtime'}</h2>
        {#if state.installed}
          <div class="tabs" aria-label="Installation sections"><button class:active={installedSection==='runtime'} on:click={()=>installedSection='runtime'}>Runtime</button><button class:active={installedSection==='storage'} on:click={()=>installedSection='storage'}>Storage and skill</button></div>
          {#if installedSection==='runtime'}
            <p>Desktop {state.release?.version} · Runtime {state.currentVersion??'installed'}</p>
            <details class="runtime-digest"><summary>Image identity</summary><code>{state.currentDigest}</code></details>
            {#if !state.container?.exists}<p class="hint">The container has been removed. Your stored data are kept.</p>{/if}
            {#if state.updatePending}<p class="hint">Recover the interrupted update before starting the game or removing the container.</p>{/if}
            <div class="toolbar"><button disabled={busy||(!state.updatePending&&!state.cleanupPending&&!state.updateRequired&&state.container?.exists)} on:click={()=>task(()=>window.astra.invoke('update'),'Runtime ready.')}>{state.updatePending?'Recover interrupted update':!state.container?.exists?'Recreate container':state.updateRequired?'Update runtime':state.cleanupPending?'Retry cleanup':'Runtime matches Desktop'}</button></div>
            {#if state.previousRuntime}<p class="hint">Recovery copy: {state.previousRuntime.version??'previous runtime'} · {new Date(state.previousRuntime.created).toLocaleDateString()}</p>{/if}
            <p class="hint">Save your game and disconnect the agent before updating. One previous runtime and a copy of its saved data are kept for recovery.</p>
            {#if busy&&progress}<pre class="setup-progress">{progress}</pre>{/if}
            <div class="container-management"><h3>Container management</h3><p class="hint">Remove the container while keeping your game, saves, Atlas, notes and recordings.</p><button class="danger" disabled={busy||!state.container?.exists||state.updatePending} on:click={async()=>{const result=await task(()=>window.astra.invoke('remove-container'));if(result?.removed)notice='Container removed. Your stored data are kept.';}}>Remove container</button></div>
          {:else}
            <p>Game files: <code>{state.sourceGame}</code></p><p class="hint">{state.gameMode==='copy'?'Managed copy':'Read-only host folder'}</p>
            <p>Managed storage: <code>{state.storageDirectory}</code></p>
            <p>Recordings: <code>{state.recordingsDirectory}</code></p>
            <div class="toolbar"><button on:click={()=>task(()=>window.astra.invoke('open-recordings-folder'))}><Icon name="folder" size={20}/>Open recordings folder</button><button on:click={()=>task(()=>window.astra.invoke('skill-export'),'Skill exported.')}><Icon name="export" size={20}/>Export gameplay skill</button></div>
          {/if}
        {:else}
          <div class="tabs" aria-label="Setup steps"><button class:active={setupStep==='game'} on:click={()=>setupStep='game'}>1. Game</button><button class:active={setupStep==='storage'} on:click={()=>setupStep='storage'}>2. Storage</button></div>
          <div class="setup-fields">
          {#if setupStep==='game'}
            <label>Morrowind installation<div class="field-row"><input bind:value={game} placeholder="Choose your existing Morrowind folder"><button on:click={()=>choose('game')}><Icon name="folder" size={17}/>Browse</button></div></label>
            <label>Game data source<select bind:value={gameMode}><option value="mount">Use the host folder — no copying (default)</option><option value="copy">Copy into managed storage</option></select></label>
            <p class="hint">{gameMode==='mount'?'Host edits are visible to the runtime. Stop the game before editing the source folder.':'The managed copy is independent of later changes to the original folder.'}</p>
            <div class="form-grid"><label>Data directory inside the game folder<input bind:value={dataRelative} placeholder="Data Files"></label>
            <label>Game text encoding<select bind:value={encoding}><option value="win1251">Windows-1251 (Cyrillic)</option><option value="win1252">Windows-1252 (Western European)</option><option value="win1250">Windows-1250 (Central European)</option></select></label></div>
            <p class="hint">Active plugins and archives are read from Morrowind.ini. If no INI is present, configure the content list in Settings before starting.</p>
          {:else}
            <label>Managed storage<div class="field-row"><input bind:value={storage} placeholder="Choose a storage location"><button on:click={()=>choose('storage')}><Icon name="folder" size={17}/>Browse</button></div></label>
            <label>Recordings folder on this computer<div class="field-row"><input bind:value={recordingsDirectory} placeholder="Defaults to recordings inside managed storage"><button on:click={()=>choose('recordings')}><Icon name="folder" size={17}/>Browse</button></div></label>
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
    {:else if page==='profiles'&&state.installed}
      <section class="card profiles-card">
        <div class="section-heading"><div><h2>Playthrough profiles</h2><p class="hint">Separate saves, Atlas, knowledge, notes and session history.</p></div><button disabled={runtime.running||busy} on:click={()=>profileEdit('create')}><Icon name="plus" size={18}/>New profile</button></div>
        {#if runtime.running}<div class="profile-lock"><span class="hint">Stop the game to create, switch, rename, copy or delete profiles. Save your progress first.</span><button disabled={busy} on:click={()=>task(()=>window.astra.invoke('stop-game'))}>Stop game</button></div>{/if}
        <div class="profile-grid">
          <div class="scroll-region" aria-label="Profile list">{#each profiles as profile}<button class="node-row" class:selected={selectedProfile?.id===profile.id} on:click={()=>{selectedProfile=profile;profileForm='';}}><strong>{profile.name}</strong><span>{profile.active?'Active profile':'Available'} · {new Date(profile.created*1000).toLocaleDateString()}</span></button>{/each}</div>
          <div class="profile-detail">
            {#if selectedProfile}<h3>{selectedProfile.name}</h3><p class="hint">{selectedProfile.active?'The game and agent use this profile.':'Switch to this profile before starting the game.'}</p>{/if}
            <fieldset disabled={runtime.running||busy}>
              {#if profileForm}
                <form on:submit|preventDefault={()=>changeProfile(profileForm)}>
                  <label>{profileForm==='duplicate'?'Copy name':profileForm==='rename'?'New name':'Profile name'}<input aria-label="Profile name" maxlength="80" bind:value={profileName} required></label>
                  <p class="hint">{profileForm==='duplicate'?'Copies saves, Atlas, knowledge, notes, settings and history. The copy is independent. Existing videos are kept with the original profile.':profileForm==='create'?'Starts with empty saves and memory, using your current game settings.':'The profile’s data and exported skill binding stay the same.'}</p>
                  <div class="toolbar"><button class="primary" type="submit" disabled={!profileName.trim()}>{profileForm==='duplicate'?'Create copy':profileForm==='rename'?'Save name':'Create profile'}</button><button type="button" on:click={()=>profileForm=''}>Cancel</button></div>
                </form>
              {:else if selectedProfile}
                <div class="profile-actions"><button class="primary" disabled={selectedProfile.active} on:click={()=>changeProfile('switch')}>{selectedProfile.active?'Active profile':'Use this profile'}</button><button on:click={()=>profileEdit('rename')}>Rename</button><button on:click={()=>profileEdit('duplicate')}><Icon name="copy" size={18}/>Duplicate profile</button><button class="danger" on:click={()=>changeProfile('delete')}>Delete profile</button></div>
                <p class="hint">New profiles share no memories. Duplicate makes an independent copy at the time you choose.</p>
                <p class="hint">Export a gameplay skill for the selected active profile before connecting an agent.</p>
              {/if}
            </fieldset>
          </div>
        </div>
      </section>
    {:else if page==='atlas'&&state.installed}
      <section class="card atlas-card"><div class="section-heading"><div><h2>Travelled world</h2><p>Places and routes learned in this profile.</p></div><div class="toolbar"><select aria-label="Atlas location" bind:value={space} on:change={loadAtlas}><option value="">Current location</option>{#each atlas.spaces??[] as location}<option value={location.ref}>{location.location??location.label??location.ref}</option>{/each}</select><button on:click={loadAtlas}><Icon name="restart" size={18}/>Refresh</button></div></div>
        {#if atlas.supported}<div class="atlas-grid"><div class="map-pane">{#if atlas.svg}<img class="atlas-image" src={artifact(atlas.svg)} alt="Map of travelled routes">{/if}<p>{atlas.location} · {atlas.recorded_points??0} recorded points</p></div>
        <div class="scroll-region"><h3>Visited points</h3>{#each atlas.nodes??[] as node}<button class="node-row" class:selected={selectedNode?.ref===node.ref} on:click={()=>selectedNode=node}><strong>{node.label}</strong><span>{node.distance_m} m · {node.visits} visits</span></button>{/each}</div></div>
        {#if selectedNode}<section class="details"><h3>{selectedNode.label}</h3><p>{selectedNode.location}</p><p>{selectedNode.names?.join(', ')}</p><p>Route distance: {selectedNode.route_distance_m??'Unknown'} m · {selectedNode.can_revisit?'Route available':'No current route'}</p>{#each selectedNode.landmarks??[] as landmark}<p>{typeof landmark==='string'?landmark:landmark.name??landmark.label??landmark.kind}</p>{/each}</section>{/if}
        {#if atlas.transitions?.length}<h3>Transitions</h3><pre>{JSON.stringify(atlas.transitions,null,2)}</pre>{/if}
        {:else}<div class="empty"><p>No travelled map yet. Explore the game to build the Atlas.</p></div>{/if}
      </section>
    {:else if page==='recordings'&&state.installed}
      <section class="card recordings-card"><div class="section-heading"><h2>Recordings</h2><div class="toolbar"><button disabled={!runtime.running||busy} on:click={()=>task(()=>window.astra.invoke('record',{action:runtime.recording?'stop':'start'}))}><Icon name="record" size={20}/>{runtime.recording?'Stop recording':'Start recording'}</button><button on:click={()=>task(()=>window.astra.invoke('open-recordings-folder'))}><Icon name="folder" size={20}/>Open folder</button><button on:click={loadRecordings}><Icon name="restart" size={18}/>Refresh</button></div></div>
        <p class="hint">{state.recordingsDirectory}</p>
        <div class="recording-grid"><div class="scroll-region">{#each recordings as row}<button class="node-row" class:selected={selectedRecording?.id===row.id} on:click={()=>selectRecording(row)}><strong>{row.name}</strong><span>{new Date(row.created*1000).toLocaleString()} · {formatBytes(row.bytes)}</span></button>{:else}<p>No recordings yet.</p>{/each}</div>
        <div class="recording-preview">{#if selectedRecording}<!-- svelte-ignore a11y_media_has_caption --><video class="playback" src={artifact(selectedRecording.video)} controls></video><div class="toolbar"><button on:click={()=>task(()=>window.astra.invoke('export-artifact',{path:selectedRecording.video,name:selectedRecording.name}),'Recording exported.')}><Icon name="export" size={18}/>Export MP4</button>{#if selectedRecording.metadata}<button on:click={()=>task(()=>window.astra.invoke('export-artifact',{path:selectedRecording.metadata,name:selectedRecording.name+'.json'}),'Metadata exported.')}><Icon name="export" size={18}/>Export metadata</button>{/if}</div>{#if metadata}<details><summary>Recording metadata</summary><pre>{JSON.stringify(metadata,null,2)}</pre></details>{/if}{:else}<div class="empty"><p>Select a recording to play or export it.</p></div>{/if}</div></div>
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
      <section class="card diagnostics-card"><div class="section-heading"><h2>Runtime diagnostics</h2><button on:click={loadDiagnostics}><Icon name="restart" size={18}/>Refresh</button></div>
        <div class="status-grid" inert={fullscreen}><div class="metric"><small>CAPTURE</small><strong>{Math.max(0,runtime.capture_fps??0).toFixed(1)} fps</strong></div><div class="metric"><small>VIEWER</small><strong>{runtime.viewer?.quality??'Off'}</strong></div><div class="metric"><small>ENCODER</small><strong>{runtime.viewer?.encoder?.encoder??'Not active'}</strong></div><div class="metric"><small>LIVE AUDIO GAPS</small><strong>{runtime.viewer?.audio_discontinuities??0}</strong></div></div>
        <div class="section-heading"><div class="tabs" aria-label="Diagnostic sections">{#each [['logs','Logs'],['environment','Environment'],['sessions','Sessions']] as [id,label]}<button class:active={diagnosticSection===id} aria-pressed={diagnosticSection===id} on:click={()=>diagnosticSection=id}>{label}</button>{/each}</div>
        {#if diagnosticSection==='logs'}<select aria-label="Diagnostic log" bind:value={logName} on:change={loadDiagnostics}>{#each logs.names?.length?logs.names:['daemon.log'] as name}<option>{name}</option>{/each}</select>{/if}</div>
        <pre class="log">{diagnosticSection==='logs'?logs.text||'No log output yet.':JSON.stringify(diagnosticSection==='environment'?environment:history,null,2)}</pre>
      </section>
    {/if}
  </main>
</div>
