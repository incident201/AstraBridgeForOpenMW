<script lang="ts">
  import {onMount} from 'svelte';
  import Icon from './Icon.svelte';
  import AtlasMap from './AtlasMap.svelte';
  import {ReplayViewer,type ReplayInfo} from './replay';
  import {Viewer,artifact,pointer} from './viewer';
  const pages=[['play','Play'],['atlas','Atlas'],['recordings','Recordings'],['profiles','Profiles'],['settings','Settings'],['diagnostics','Diagnostics'],['setup','Setup']];
  let page='play',state:any={installed:false},runtime:any={},busy=false,error='',notice='',progress='';
  let game='',storage='',recordingsDirectory='',encoding='win1251',dataRelative='Data Files',development=false;
  let gameMode:'mount'|'copy'='mount';
  let setupStep='game',installedSection='runtime',settingsSection='data',diagnosticSection='logs';
  let video:HTMLVideoElement,viewer=new Viewer(),watching=false,quality='720p30',muted=false;
  let fullscreen=false,fullscreenControls=true,fullscreenTimer:ReturnType<typeof setTimeout>,pointerCaptured=false;
  let replayVideo:HTMLVideoElement,replay:ReplayViewer|null=null,viewMode:'live'|'replay'|'still'='live';
  let replayInfo:ReplayInfo={id:null,ready:false,active:false,duration:0},replayPosition=0,replayPlaying=false,replayBusy=false,replayError='';
  let seekDraft=0,seeking=false,seekSerial=0,pollingReplay=false;
  let gpus:any[]=[];
  let configuration:any=null,content='',archives='',recordings:any[]=[],selectedRecording:any=null,metadata:any=null;
  let atlas:any={},space='',selectedNode:any=null,atlasSection='points',mapRadius=35,atlasPage=0,expandedMap=false,metadataOpen=false,logName='daemon.log',logs:any={names:[],text:''},environment:any={},history:any[]=[];
  let profiles:any[]=[],selectedProfile:any=null,profileForm='',profileName='',lastProfile='';
  let mapView:AtlasMap,mapRevision=0;
  $: owner=runtime.owner?.mode??'idle';
  $: manual=owner==='manual';
  $: recording=Boolean(runtime.recording?.recording);
  $: replayAvailable=replayInfo.ready&&Boolean(state.container?.running);
  $: playbackRunning=viewMode==='replay'?replayPlaying:viewMode==='live'&&watching;
  $: timelinePosition=seeking?seekDraft:viewMode==='live'?(watching?replayInfo.duration:0):Math.min(replayPosition,replayInfo.duration);
  $: if(runtime.profile?.id&&runtime.profile.id!==lastProfile){
    lastProfile=runtime.profile.id;atlas={};space='';selectedNode=null;atlasPage=0;atlasSection='points';mapRadius=35;expandedMap=false;recordings=[];selectedRecording=null;metadata=null;metadataOpen=false;history=[];logs={names:[],text:''};configuration=null;
    replayInfo={id:null,ready:false,active:false,duration:0};replay?.close();replay=null;viewMode='live';
  }
  $: if(owner!=='manual'&&typeof document!=='undefined'&&document.pointerLockElement)void document.exitPointerLock();

  async function refresh(){
    try{state=await window.astra.invoke('status');if(state.runtime)runtime=state.runtime;else runtime={};}
    catch(e){error=(e as Error).message;}
  }
  async function task(action:()=>Promise<any>,message=''){
    closeMenus();
    busy=true;error='';notice='';
    try{const result=await action();if(message)notice=message;await refresh();return result;}
    catch(e){error=(e as Error).message;}
    finally{busy=false;}
  }
  async function navigate(next:string){
    closeMenus();
    if(page==='play'&&next!=='play')await endWatch();
    page=next;error='';
    if(next==='recordings')await loadRecordings();
    if(next==='atlas')await loadAtlas();
    if(next==='settings')await task(async()=>{configuration=await window.astra.invoke('configuration');gpus=await window.astra.invoke('gpus');content=configuration.content.join('\n');archives=configuration.archives.join('\n');});
    if(next==='diagnostics')await loadDiagnostics();
    if(next==='profiles')await loadProfiles();
  }
  async function loadProfiles(){await task(async()=>{const data=await window.astra.invoke('profiles');profiles=data.profiles;selectedProfile=profiles.find(p=>p.id===selectedProfile?.id)??profiles.find(p=>p.active);profileForm='';});}
  function profileEdit(operation:string){profileForm=operation;profileName=operation==='rename'?selectedProfile.name:operation==='duplicate'?selectedProfile.name.slice(0,75)+' copy':'';}
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
      }else if(replayAvailable)await seekReplay(watching?replayInfo.duration:0,!watching);
      else {replayPosition=runtime.recording?.duration??0;await reviewMode('still');video.pause();}
    }catch(e){replayError=(e as Error).message;}
  }
  function replayTime(){if(viewMode==='replay'&&replay)replayPosition=replay.position;}
  function changeMute(){muted=!muted;video.muted=muted||viewMode!=='live';if(replayVideo)replayVideo.muted=muted;}
  function formatTime(value:number){
    const seconds=Math.max(0,Number.isFinite(value)?value:0),minutes=Math.floor(seconds/60);
    return (minutes>=60?Math.floor(minutes/60)+':'+String(minutes%60).padStart(2,'0'):String(minutes))+':'+String(Math.floor(seconds%60)).padStart(2,'0');
  }
  function closeMenus(){document.querySelectorAll<HTMLDetailsElement>('details.dropdown[open]').forEach(menu=>menu.open=false);}
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
    try{closeMenus();input({type:'release'});const result=await window.astra.invoke('viewer-fullscreen',{enabled:!fullscreen});setViewerFullscreen(result.enabled);video.focus();}
    catch(e){error=(e as Error).message;}
  }
  async function changeQuality(){if(watching)await watch();}
  async function togglePointerCapture(){
    try{if(document.pointerLockElement===video)document.exitPointerLock();else {video.focus();await video.requestPointerLock();}}
    catch(e){error=(e as Error).message;}
  }
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
  async function loadRecordings(){await task(async()=>{recordings=await window.astra.invoke('recordings');if(!recordings.some(row=>row.id===selectedRecording?.id)){selectedRecording=null;metadata=null;metadataOpen=false;}});}
  async function selectRecording(row:any){selectedRecording=row;metadata=null;metadataOpen=false;if(row.metadata)await task(async()=>{metadata=await window.astra.invoke('artifact-json',{path:row.metadata});});}
  async function loadAtlas(){await task(async()=>{atlas=await window.astra.invoke('atlas',{...(space?{space}:{}),radius_m:mapRadius,page:atlasPage,limit:100});mapRevision++;selectedNode=null;});}
  async function loadDiagnostics(){await task(async()=>{logs=await window.astra.invoke('logs',{name:logName});
    if(state.container?.running){environment=await window.astra.invoke('environment');history=await window.astra.invoke('sessions');}});}
  const formatBytes=(n:number)=>n>1024**3?(n/1024**3).toFixed(2)+' GB':(n/1024**2).toFixed(1)+' MB';
  const distance=(n:number)=>Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:2})+' m':'Unknown';
  const locationName=(ref:string)=>atlas.spaces?.find((item:any)=>item.ref===ref)?.location??'Recorded location';
  const eventName=(value:string)=>({engine_started:'Game started',engine_stopped:'Game stopped',agent_connected:'Agent connected',owner_disconnected:'Controller disconnected',profile_switched:'Profile switched'}[value]??value.replaceAll('_',' '));
  const displayValue=(value:any):string=>value==null?'Not available':typeof value==='boolean'?(value?'Yes':'No'):typeof value==='object'?Object.entries(value).map(([key,item])=>key.replaceAll('_',' ')+': '+displayValue(item)).join(' · '):String(value);

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
    const pointerLockChanged=()=>{pointerCaptured=document.pointerLockElement===video;if(!document.pointerLockElement)revealFullscreenControls();};
    const outsideMenu=(event:MouseEvent)=>{
      const active=(event.target as Element)?.closest('details.dropdown');
      document.querySelectorAll<HTMLDetailsElement>('details.dropdown[open]').forEach(menu=>{if(menu!==active)menu.open=false;});
    };
    const menuEscape=(event:KeyboardEvent)=>{
      const menu=(event.target as Element)?.closest<HTMLDetailsElement>('details.dropdown[open]');
      if(event.key==='Escape'&&menu){event.preventDefault();event.stopPropagation();menu.open=false;menu.querySelector('summary')?.focus();}
    };
    document.addEventListener('click',outsideMenu);
    document.addEventListener('keydown',menuEscape);
    document.addEventListener('mousemove',revealFullscreenControls);
    document.addEventListener('pointerlockchange',pointerLockChanged);
    window.addEventListener('blur',releaseInput);
    return()=>{clearInterval(timer);clearInterval(replayTimer);replay?.close();clearTimeout(fullscreenTimer);unsubscribe();releaseInput();void viewer.close();
      document.removeEventListener('mousemove',revealFullscreenControls);document.removeEventListener('pointerlockchange',pointerLockChanged);window.removeEventListener('blur',releaseInput);
      document.removeEventListener('click',outsideMenu);document.removeEventListener('keydown',menuEscape);};
  });
</script>

<svelte:head><title>AstraBridge</title></svelte:head>
<div class="app-shell" class:play-shell={page==='play'}>
  <aside inert={fullscreen}>
    <div class="brand"><span class="brand-mark">A</span><div>AstraBridge<small>OPENMW<br>RUNTIME</small></div></div>
    <nav aria-label="Main navigation">
      {#each pages as [id,label]}<button class:active={page===id} aria-current={page===id?'page':undefined} title={label} on:click={()=>navigate(id)}><Icon name={id}/><span>{label}</span></button>{/each}
    </nav>
    <div class="sidebar-footer" title={state.container?.running?'Runtime running':state.installed?'Runtime stopped':'Not installed'}><span class:online={state.container?.running} class="dot"></span><span class="runtime-label">{state.container?.running?'Runtime running':state.installed?'Runtime stopped':'Not installed'}</span>
      {#if runtime.profile}<small class="active-profile" title={runtime.profile.name}>Profile · {runtime.profile.name}</small>{/if}
      <small>{state.release?.version??''} · {state.backend??'Linux / Windows'}</small>
    </div>
  </aside>
  <main class:play-page={page==='play'} class:management-page={page!=='play'}>
    <header inert={fullscreen}><div class="page-title"><div><p class="eyebrow">ASTRABRIDGE</p><h1>{pages.find(([id])=>id===page)?.[1]}</h1></div>
      {#if runtime.profile}<button class="profile-link" title={'Manage profile: '+runtime.profile.name} on:click={()=>navigate('profiles')}><Icon name="profiles" size={16}/><span>{runtime.profile.name}</span><Icon name="chevron" size={14}/></button>{/if}</div>
      <div class="toolbar">
        {#if state.installed}
          <span class="game-state"><span class="dot" class:online={runtime.running}></span>{runtime.running?'Game running':'Game stopped'}</span>
          <details class="dropdown session-menu"><summary aria-label="Session options"><Icon name="more" size={19}/><span>Session</span></summary>
            <div class="menu-popover">
              <div class="menu-label">Runtime</div>
              <button disabled={busy||runtime.running||!state.container?.exists} on:click={()=>task(()=>window.astra.invoke('start'))}><Icon name="play" size={17}/>Start game</button>
              <button disabled={busy||!state.container?.running} on:click={()=>task(async()=>{await endWatch();return window.astra.invoke('stop');})}><Icon name="stop" size={17}/>Stop runtime</button>
              <button disabled={busy} on:click={()=>task(async()=>{await endWatch();return window.astra.invoke('restart');})}><Icon name="restart" size={17}/>Restart</button>
              <div class="menu-divider"></div>
              <button on:click={()=>task(()=>window.astra.invoke('skill-export'),'Skill exported. Give the exported folder to your agent.')}><Icon name="export" size={17}/>Export gameplay skill</button>
              {#if owner==='agent'}<button class="danger" on:click={()=>task(()=>window.astra.invoke('agent-end'),'Agent session ended. Manual control is now available.')}><Icon name="disconnect" size={17}/>End agent session</button>{/if}
            </div>
          </details>
        {/if}
      </div>
    </header>
    {#if state.installed&&(state.updatePending||state.updateRequired)&&page!=='setup'}<div class="banner" role="status"><span>{state.updatePending?'A runtime update was interrupted. Open Setup to recover your previous runtime.':'This Desktop needs its matching runtime. Open Setup to update; your saved data will be kept.'}</span><button class="banner-action" on:click={()=>navigate('setup')}>Open setup</button></div>{/if}
    {#if error&&!fullscreen}<div role="alert" class="banner error">{error}<button on:click={()=>error=''} aria-label="Dismiss error">×</button></div>{/if}
    {#if notice&&!fullscreen}<div role="status" class="banner">{notice}<button on:click={()=>notice=''} aria-label="Dismiss notification">×</button></div>{/if}
    {#if busy}<div class="working" role="status">Working…</div>{/if}
    {#if !state.installed&&page!=='setup'}<section class="empty"><h2>Set up your game</h2><p>Import your Morrowind installation and install the AstraBridge runtime.</p><button class="primary" on:click={()=>navigate('setup')}>Open setup</button></section>{/if}

    {#if page==='play'&&state.installed}
      <section class="viewer-panel" class:fullscreen-controls={fullscreenControls} class:viewer-fullscreen={fullscreen} aria-labelledby="live-view-title">
        {#if fullscreen&&error}<div class="viewer-alert error" role="alert"><span>{error}</span><button class="icon-button" on:click={()=>error=''} aria-label="Dismiss error">×</button></div>{/if}
        {#if fullscreen&&notice&&!error}<div class="viewer-alert" role="status"><span>{notice}</span><button class="icon-button" on:click={()=>notice=''} aria-label="Dismiss notification">×</button></div>{/if}
        <div class="section-heading">
          <div class="viewer-heading">
            <h2 id="live-view-title">{viewMode==='live'?(watching?'Live view':'Game view'):'Playback'}</h2>
            <span class="controller-state" class:agent={owner==='agent'} title={runtime.owner?.name??'No active controller'}><Icon name="control" size={16}/>{owner==='agent'?'Agent connected':manual?'Manual control':'No controller'}</span>
            {#if runtime.active_action?.operation}<span class="action-state" title={runtime.active_action.operation+' · '+(runtime.active_action.phase??'')}><span class="action-dot"></span><span class="action-name">{runtime.active_action.operation}</span></span>{/if}
          </div>
          <div class="viewer-tools">
            <button class="record-button" class:recording aria-label={recording?'Stop recording':'Start recording'} title={recording?'Stop recording':'Record at 1080p · 60 fps'} disabled={!runtime.running||busy} on:click={()=>task(()=>window.astra.invoke('record',{action:recording?'stop':'start'}))}><Icon name={recording?'stop':'record'} size={17}/>{#if recording}<span class="rec-label">REC</span>{/if}<span>{recording?formatTime(runtime.recording.duration):'Record'}</span></button>
            <details class="dropdown viewer-options"><summary class="icon-button" aria-label="Viewer options" title="Viewer options"><Icon name="settings" size={19}/></summary>
              <div class="menu-popover">
                <label>Stream quality<select aria-label="Viewer quality" bind:value={quality} on:change={changeQuality} disabled={busy}><option value="720p30">720p · 30 fps</option><option value="1080p60">1080p · 60 fps</option></select></label>
                <p>Recordings always use 1080p · 60 fps.</p>
                <div class="menu-divider"></div>
                {#if watching}<button on:click={()=>task(endWatch)}><Icon name="disconnect" size={17}/>Disconnect viewer</button><p>The game and recording keep running.</p>{/if}
              </div>
            </details>
            <button class="icon-button" disabled={!watching&&viewMode!=='replay'} on:click={toggleFullscreen} aria-label={fullscreen?'Exit fullscreen':'Fullscreen'} title={fullscreen?'Exit fullscreen':'Fullscreen'} aria-pressed={fullscreen}><Icon name={fullscreen?'minimize':'fullscreen'} size={20}/></button>
          </div>
        </div>
        <div class="video-wrap">
          <!-- The video is an intentional keyboard/mouse game surface. -->
          <!-- svelte-ignore a11y_media_has_caption a11y_no_noninteractive_tabindex a11y_no_noninteractive_element_interactions -->
          <video class:concealed={viewMode==='replay'} bind:this={video} autoplay playsinline tabindex="0" aria-label="Live Morrowind game"
            on:mousemove={mousemove} on:mousedown={e=>mousebutton(e,true)} on:mouseup={e=>mousebutton(e,false)}
            on:keydown={e=>key(e,true)} on:keyup={e=>key(e,false)} on:wheel|nonpassive={wheel} on:contextmenu|preventDefault={()=>{}}></video>
          <!-- svelte-ignore a11y_media_has_caption -->
          <video class:concealed={viewMode!=='replay'} bind:this={replayVideo} playsinline aria-label="Recording replay"
            on:timeupdate={replayTime} on:seeked={replayTime} on:play={()=>replayPlaying=true} on:pause={()=>replayPlaying=false}></video>
          {#if viewMode!=='live'}<span class="replay-badge">{viewMode==='still'||!replayPlaying?'View paused':'Replay'}</span>{/if}
          {#if replayBusy}<div class="replay-loading" role="status">Loading recording…</div>{/if}
          {#if replayError}<div class="replay-error" role="alert">{replayError}</div>{/if}
          {#if !watching&&viewMode==='live'}<div class="video-placeholder"><div class="placeholder-icon"><Icon name="monitor" size={32}/></div><h3>{runtime.running?'Your game is running':'Ready when you are'}</h3><p>{runtime.running?'Connect to watch or take control.':'Start Morrowind in your current profile.'}</p>
            <div class="placeholder-actions">{#if runtime.running}<button class="primary" disabled={busy} on:click={watch}><Icon name="play" size={17}/>Open viewer</button>
            {:else}<button class="primary" disabled={busy||!state.container?.exists||state.updateRequired||state.updatePending} on:click={()=>task(()=>window.astra.invoke('start'))}><Icon name="play" size={17}/>Start game</button>{/if}
            {#if replayAvailable}<button disabled={replayBusy} on:click={()=>seekReplay(0,true)}><Icon name="recordings" size={17}/>Review recording</button>{/if}</div>
          </div>{/if}
        </div>
        <div class="viewer-controls">
          <div class="timeline" aria-label="Viewer playback">
            <button class="playback-toggle" aria-label={playbackRunning?'Pause playback':!watching&&viewMode==='live'?'Play recording':'Play playback'} title="Playback only; the game continues" disabled={replayBusy||(!watching&&!replayAvailable)} on:click={togglePlayback}><Icon name={playbackRunning?'pause':'play'} size={19}/></button>
            <input class="timeline-range" aria-label="Recording timeline" type="range" min="0" max={Math.max(.001,replayInfo.duration)} step="0.01"
              disabled={!replayAvailable} value={timelinePosition}
              on:input={event=>{seeking=true;seekDraft=Number(event.currentTarget.value);}}
              on:change={()=>seekReplay(seekDraft,viewMode==='replay'&&replayPlaying)}>
            <span class="timeline-time">{replayAvailable?formatTime(timelinePosition)+' / '+formatTime(replayInfo.duration):recording||replayInfo.active?'Preparing recording…':'Recording is off'}</span>
            <button class="live-button" class:active={watching&&viewMode==='live'} aria-label={watching?'Return to live':'Connect live view'} disabled={!watching&&!runtime.running} on:click={()=>void goLive().catch(e=>replayError=e.message)}><span class="live-dot"></span>{viewMode!=='live'?'Go live':watching?'Live':runtime.running?'Connect':'Offline'}</button>
          </div>
          <div class="input-controls">
            <button class="icon-button" disabled={!watching&&viewMode!=='replay'} on:click={changeMute} aria-label={muted?'Unmute':'Mute'} title={muted?'Unmute':'Mute'}><Icon name={muted?'mute':'volume'} size={18}/></button>
            {#if viewMode!=='live'}<span class="view-only" title="Game input is disabled while reviewing. Gameplay and recording continue."><Icon name="lock" size={15}/>View only</span>
            {:else if manual}<button class="manual-button" on:click={releaseInput}><Icon name="cursor" size={17}/>Release control</button><button class="camera-button" aria-label={pointerCaptured?'Release pointer':'Lock pointer for camera'} aria-pressed={pointerCaptured} title="Capture the mouse to look around. Escape releases it." on:click={togglePointerCapture}><Icon name="mouse" size={17}/>{pointerCaptured?'Release mouse':'Capture mouse'}</button>
            {:else}<button class="manual-button" disabled={!watching||owner==='agent'} title={owner==='agent'?'End the agent session before taking manual control.':'Control the game with your keyboard and mouse'} on:click={()=>window.astra.input({type:'manual.acquire'})}><Icon name="cursor" size={17}/>{owner==='agent'?'Agent owns input':'Take manual control'}</button>{/if}
          </div>
        </div>
      </section>
      <div class="play-footer" inert={fullscreen}>
        <span class="graphics-status" title={runtime.graphics?.renderer??'Private display'}><Icon name="monitor" size={14}/><span>{viewMode!=='live'?'Playback only · gameplay and recording continue':runtime.graphics?.renderer??'Private game display'}</span></span>
        <div class="footer-tools">{#if runtime.running&&runtime.game_fps!=null}<span class="fps-counter">{Math.round(runtime.game_fps)} <span>fps</span></span>{/if}
          <details class="dropdown help-menu"><summary aria-label="Viewer help" title="Viewer help"><Icon name="help" size={16}/></summary><div class="menu-popover">
            <strong>Watching &amp; playing</strong><p>The timeline controls your view only. Gameplay and recording continue in the background.</p>
            <p>Take manual control when no agent is connected. Lock the pointer to look around; Escape releases pointer lock. Escape may also open the in-game menu.</p>
            <p>Leaving the window releases manual control. Use the fullscreen button to exit fullscreen.</p>
          </div></details>
        </div>
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
            {#if state.updatePending||state.cleanupPending||state.updateRequired||!state.container?.exists}<div class="toolbar"><button class="primary" disabled={busy} on:click={()=>task(()=>window.astra.invoke('update'),'Runtime ready.')}>{state.updatePending?'Recover interrupted update':!state.container?.exists?'Recreate container':state.updateRequired?'Update runtime':'Retry cleanup'}</button></div>
            {:else}<p class="runtime-match"><span class="dot online"></span>Runtime matches Desktop</p>{/if}
            {#if state.previousRuntime}<p class="hint">Recovery copy: {state.previousRuntime.version??'previous runtime'} · {new Date(state.previousRuntime.created).toLocaleDateString()}</p>{/if}
            <p class="hint">Save your game and disconnect the agent before updating. One previous runtime and a copy of its saved data are kept for recovery.</p>
            {#if busy&&progress}<pre class="setup-progress">{progress}</pre>{/if}
            <div class="container-management"><h3>Container management</h3><p class="hint">Remove the container while keeping your game, saves, Atlas, notes and recordings.</p><button class="danger" disabled={busy||!state.container?.exists||state.updatePending} on:click={async()=>{const result=await task(()=>window.astra.invoke('remove-container'));if(result?.removed)notice='Container removed. Your stored data are kept.';}}>Remove container</button></div>
          {:else}
            <dl class="storage-locations"><div><dt>Game files <span>{state.gameMode==='copy'?'Managed copy':'Read-only host folder'}</span></dt><dd><code>{state.sourceGame}</code></dd></div>
            <div><dt>Managed storage</dt><dd><code>{state.storageDirectory}</code></dd></div><div><dt>Recordings</dt><dd><code>{state.recordingsDirectory}</code></dd></div></dl>
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
            {#if profileForm}<h3>{profileForm==='create'?'New profile':profileForm==='duplicate'?'Copy profile':'Rename profile'}</h3>{#if profileForm!=='create'}<p class="hint">{selectedProfile?.name}</p>{/if}
            {:else if selectedProfile}<h3>{selectedProfile.name}</h3><p class="hint">{selectedProfile.active?'The game and agent use this profile.':'Switch to this profile before starting the game.'}</p>{/if}
            <div>
              {#if profileForm}
                <form on:submit|preventDefault={()=>changeProfile(profileForm)}>
                  <label>{profileForm==='duplicate'?'Copy name':profileForm==='rename'?'New name':'Profile name'}<input aria-label="Profile name" maxlength="80" bind:value={profileName} required disabled={runtime.running||busy}></label>
                  <p class="hint">{profileForm==='duplicate'?'Copies saves, Atlas, knowledge, notes, settings and history. The copy is independent. Existing videos are kept with the original profile.':profileForm==='create'?'Starts with empty saves and memory, using your current game settings.':'The profile’s data and exported skill binding stay the same.'}</p>
                  <div class="toolbar"><button class="primary" type="submit" disabled={runtime.running||busy||!profileName.trim()}>{profileForm==='duplicate'?'Create copy':profileForm==='rename'?'Save name':'Create profile'}</button><button type="button" disabled={busy} on:click={()=>profileForm=''}>Cancel</button></div>
                </form>
              {:else if selectedProfile}
                <fieldset class="profile-actions" disabled={runtime.running||busy}><button class="primary" disabled={selectedProfile.active} on:click={()=>changeProfile('switch')}>{selectedProfile.active?'Active profile':'Use this profile'}</button><button on:click={()=>profileEdit('rename')}>Rename</button><button on:click={()=>profileEdit('duplicate')}><Icon name="copy" size={18}/>Duplicate profile</button><button class="danger" on:click={()=>changeProfile('delete')}>Delete profile</button></fieldset>
                <p class="hint">New profiles share no memories. Duplicate makes an independent copy at the time you choose.</p>
                <p class="hint">Export a gameplay skill for the selected active profile before connecting an agent.</p>
              {/if}
            </div>
          </div>
        </div>
      </section>
    {:else if page==='atlas'&&state.installed}
      <section class="card atlas-card">
        <div class="section-heading"><div><h2 title={atlas.location??'Travelled world'}>{atlas.location??'Travelled world'}</h2><p class="hint">Known routes in this profile · north is up</p></div>
          <div class="toolbar atlas-toolbar"><select aria-label="Atlas location" bind:value={space} on:change={()=>{atlasPage=0;void loadAtlas();}}><option value="">Current location</option>{#each atlas.spaces??[] as location}<option value={location.ref}>{location.location??location.label??location.ref}</option>{/each}</select>
          <button class="icon-button" disabled={busy} on:click={loadAtlas} aria-label="Refresh Atlas" title="Refresh Atlas"><Icon name="restart" size={18}/></button>
          <button class="icon-button" aria-label={expandedMap?'Show map sidebar':'Expand map'} title={expandedMap?'Show points and transitions':'Expand map'} aria-pressed={expandedMap} on:click={()=>expandedMap=!expandedMap}><Icon name="panel" size={18}/></button></div>
        </div>
        {#if atlas.supported}<div class="atlas-grid" class:map-expanded={expandedMap}>
          <div class="map-pane">{#if atlas.svg}<AtlasMap bind:this={mapView} src={artifact(atlas.svg)+'?revision='+mapRevision} markers={atlas.map_markers??[]} bounds={atlas.map_bounds} selected={selectedNode?.ref} on:select={event=>{selectedNode=atlas.nodes?.find((node:any)=>node.ref===event.detail);atlasSection='points';expandedMap=false;}}/>{:else}<div class="empty"><p>No map image is available.</p></div>{/if}
            <div class="map-caption"><label>Area<select aria-label="Map area" bind:value={mapRadius} on:change={()=>{atlasPage=0;void loadAtlas();}}><option value={35}>35 m</option><option value={100}>100 m</option><option value={500}>500 m</option></select></label><span title="Cyan lines are travelled paths. Grey indicates another height. Dashed directions have not been travelled."><i></i>Travelled path</span><span>{atlas.recorded_points??0} samples</span></div>
          </div>
          {#if !expandedMap}<div class="atlas-sidebar">
            <div class="tabs" aria-label="Atlas sections"><button class:active={atlasSection==='points'} aria-pressed={atlasSection==='points'} on:click={()=>{atlasSection='points';selectedNode=null;}}>Visited points</button><button class:active={atlasSection==='transitions'} aria-pressed={atlasSection==='transitions'} on:click={()=>{atlasSection='transitions';selectedNode=null;}}>Transitions</button></div>
            {#if selectedNode}<div class="node-details scroll-region"><button class="back-button" on:click={()=>selectedNode=null}>← Back to points</button><h3>{selectedNode.label}</h3><p>{selectedNode.location}</p>
              {#if atlas.map_markers?.some((marker:any)=>marker.ref===selectedNode.ref)}<button class="locate-point" on:click={()=>mapView?.focus(selectedNode.ref)}>Locate on map</button>{/if}
              <dl class="property-list"><div><dt>Distance</dt><dd>{distance(selectedNode.distance_m)}</dd></div><div><dt>Visits</dt><dd>{selectedNode.visits}</dd></div><div><dt>Recorded route</dt><dd>{distance(selectedNode.route_distance_m)}</dd></div><div><dt>Return route</dt><dd>{selectedNode.can_revisit?'Available':'No current route'}</dd></div></dl>
              {#if selectedNode.names?.length}<h4>Known names</h4><p>{selectedNode.names.join(', ')}</p>{/if}
              {#if selectedNode.landmarks?.length}<h4>Landmarks</h4><ul>{#each selectedNode.landmarks as landmark}<li>{typeof landmark==='string'?landmark:landmark.name??landmark.label??landmark.kind}</li>{/each}</ul>{/if}
            </div>
            {:else if atlasSection==='points'}<div class="scroll-region point-list" aria-label="Visited points">{#each atlas.nodes??[] as node}<button class="node-row" on:click={()=>selectedNode=node}><strong>{node.label}</strong><span>{distance(node.distance_m)} · {node.visits} {node.visits===1?'visit':'visits'}</span></button>{:else}<p class="hint">No points in this area. Choose a wider area or another location.</p>{/each}</div>
              {#if atlas.has_more||atlasPage>0}<div class="list-pagination"><button disabled={busy||atlasPage===0} on:click={()=>{atlasPage--;void loadAtlas();}}>Previous</button><span>{atlasPage+1}</span><button disabled={busy||!atlas.has_more} on:click={()=>{atlasPage++;void loadAtlas();}}>Next</button></div>{/if}
            {:else}<div class="scroll-region transition-list">{#each atlas.transitions??[] as transition}<article><h3>{transition.door?.name??transition.door?.description??'Recorded passage'}</h3><p>{locationName(transition.from_space)} <span aria-hidden="true">→</span> {locationName(transition.to_space)}</p><button disabled={busy} on:click={()=>{space=transition.to_space;atlasPage=0;void loadAtlas();}}>View destination</button></article>{:else}<p class="hint">No passages between locations recorded yet.</p>{/each}</div>{/if}
          </div>{/if}
        </div>
        {:else}<div class="empty section-empty"><Icon name="atlas" size={36}/><h3>No travelled map yet</h3><p>Routes and visited places appear here as you explore with this profile.</p><button on:click={()=>navigate('play')}>Go to Play</button></div>{/if}
      </section>
    {:else if page==='recordings'&&state.installed}
      <section class="card recordings-card"><div class="section-heading"><h2>Saved recordings</h2><div class="toolbar"><button disabled={!runtime.running||busy} on:click={()=>task(()=>window.astra.invoke('record',{action:recording?'stop':'start'}))}><Icon name="record" size={18}/>{recording?'Stop recording':'Start recording'}</button><button on:click={()=>task(()=>window.astra.invoke('open-recordings-folder'))}><Icon name="folder" size={18}/>Open folder</button><button class="icon-button" aria-label="Refresh recordings" title="Refresh recordings" on:click={loadRecordings}><Icon name="restart" size={18}/></button></div></div>
        <p class="hint path-text" title={state.recordingsDirectory}>{state.recordingsDirectory}</p>
        {#if recordings.length}<div class="recording-grid"><div class="scroll-region" aria-label="Recording list">{#each recordings as row}<button class="node-row" class:selected={selectedRecording?.id===row.id} on:click={()=>selectRecording(row)}><strong>{row.name}</strong><span>{new Date(row.created*1000).toLocaleString()} · {formatBytes(row.bytes)}</span></button>{/each}</div>
        <div class="recording-preview">{#if selectedRecording}<!-- svelte-ignore a11y_media_has_caption --><video class="playback" src={artifact(selectedRecording.video)} controls></video>
          <div class="toolbar recording-actions"><button on:click={()=>task(()=>window.astra.invoke('export-artifact',{path:selectedRecording.video,name:selectedRecording.name}),'Recording exported.')}><Icon name="export" size={18}/>Export MP4</button>
          {#if metadata}<button aria-expanded={metadataOpen} on:click={()=>metadataOpen=!metadataOpen}>Recording metadata</button>{/if}</div>
          {#if metadataOpen&&metadata}<section class="recording-info-panel" aria-label="Recording details"><div class="section-heading"><h3>Recording details</h3><button class="icon-button" aria-label="Close recording details" on:click={()=>metadataOpen=false}><Icon name="close" size={16}/></button></div>
            <dl class="property-list">{#each [['Video',`${metadata.width??1920} × ${metadata.height??1080} · ${metadata.fps??60} fps`],['Duration',formatTime(metadata.duration??0)],['Encoder',metadata.encoder??'Unknown'],['Hardware encoding',metadata.hardware_accelerated?'Yes':'No'],['Audio',metadata.audio_sample_rate?metadata.audio_sample_rate+' Hz':'See metadata']] as [label,value]}<div><dt>{label}</dt><dd>{value}</dd></div>{/each}</dl>
            <button on:click={()=>task(()=>window.astra.invoke('export-artifact',{path:selectedRecording.metadata,name:selectedRecording.name+'.json'}),'Metadata exported.')}><Icon name="export" size={16}/>Export metadata</button>
            <details><summary>Technical details</summary><pre>{JSON.stringify(metadata,null,2)}</pre></details>
          </section>{/if}
        {:else}<div class="empty section-empty"><Icon name="recordings" size={36}/><h3>Choose a recording</h3><p>Select a recording from the list to watch or export it.</p></div>{/if}</div></div>
        {:else}<div class="empty section-empty"><Icon name="recordings" size={36}/><h3>No recordings yet</h3><p>Start recording from Play. Videos are saved to the folder above.</p><button on:click={()=>navigate('play')}>Go to Play</button></div>{/if}
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
        {#if diagnosticSection==='logs'}<pre class="log">{logs.text||'No log output yet.'}</pre>
        {:else if diagnosticSection==='environment'}<div class="diagnostic-content scroll-region"><dl class="property-list environment-list">{#each Object.entries(environment) as [key,value]}<div><dt>{key.replaceAll('_',' ')}</dt><dd>{displayValue(value)}</dd></div>{/each}</dl></div>
        {:else}<div class="diagnostic-content scroll-region"><ol class="session-history">{#each [...history].reverse() as entry}<li><time>{new Date(entry.time*1000).toLocaleString()}</time><strong>{eventName(entry.event??'Event')}</strong>{#if entry.name}<span>{entry.name}</span>{/if}<details><summary>Details</summary><pre>{JSON.stringify(entry,null,2)}</pre></details></li>{:else}<li><p>No session history in this profile yet.</p></li>{/each}</ol></div>{/if}
      </section>
    {/if}
  </main>
</div>
