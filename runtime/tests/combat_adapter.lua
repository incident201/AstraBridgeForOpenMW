-- Actual player adapter + a delayed stock-input pulse. Reproduces the lost cast at low FPS.
package.path='mod/?.lua;'..package.path
math.atan2=math.atan2 or math.atan
local now,paused,charge,casts=0,true,20,0
local health,playerDead=50,false
local aerialMode=arg[1]=='aerial'
local verticalVelocity,denyJump,simulationTime=0,false,0
local landingDamagePending=false
local direct=aerialMode or arg[1]=='direct' or arg[1]=='modal_direct'
local modalPaused=false
local blockedShot=arg[1]=='blocked_shot'
local ranged=arg[1]=='ranged' or blockedShot
local ammo,shots,shotBusy,failShots=2,0,false,false
local submerged=false
local movementOverridden=false
local jumpPulses=0
local data,events,bindings={},{},{}
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z or 0},V)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
function V.__add(a,b)return V.new(a.x+b.x,a.y+b.y,a.z+b.z)end
function V:length()return math.sqrt(self.x^2+self.y^2+self.z^2)end
local surfaceClear=true
local aimCalls=0
local enemy={type={record=function()return {name="Visible enemy"}end}}
local object={position=V.new(0,0,0),controls={},ATTACK_TYPE={NoAttack=0,Any=1},object={},cell={id='private',displayName='Room'}}
local bus={get=function(_,k)return data[k]end,getCopy=function(_,k)return data[k]end,set=function(_,k,v)data[k]=v end}
local ring={type={record=function()return {name='Ring',enchant='private_enchantment'}end}}
local weaponType={TYPE={MarksmanThrown=1},objectIsInstance=function()return true end,
    record=function()return {type=1,name='Throwing star'}end}
local star={type=weaponType,recordId='private_star'}
local stats={dynamic={},level=function()return {current=1}end}
for _,k in ipairs({'health','magicka','fatigue'}) do stats.dynamic[k]=function()return {current=50,base=50,modifier=0}end end
stats.dynamic.health=function()return {current=health,base=50,modifier=0}end
local actor={stats=stats,objectIsInstance=function(o)return o==enemy end,getPathfindingAgentBounds=function()return {}end,getWalkSpeed=function()return 140 end,getRunSpeed=function()return 210 end,STANCE={Nothing=0,Weapon=1,Spell=2},EQUIPMENT_SLOT={CarriedRight=16},
    getStance=function()return ranged and 1 or 2 end,isOnGround=function()return not submerged and (not aerialMode or object.position.z==0) end,isSwimming=function()return submerged end,
    canMove=function()return true end,isDead=function(o)return o==object and playerDead end,
    getEquipment=function()if ranged and ammo>0 then return star end end,
    inventory=function()return {countOf=function()return ammo end}end,
    getSelectedSpell=function()end,getSelectedEnchantedItem=function()return ring end,activeSpells=function()return {}end}
package.preload['openmw.types']=function()return {Actor=actor,Weapon=ranged and weaponType or nil,Player={CONTROL_SWITCH={Controls=1,Magic=2},
    getControlSwitch=function()return true end,isCharGenFinished=function()return true end,journal=function()return {journalTextEntries={}}end}}end
package.preload['openmw.storage']=function()return {playerSection=function()return bus end}end
package.preload['openmw.self']=function()return object end
package.preload['openmw.async']=function()return {callback=function(_,f)return f end}end
package.preload['openmw.input']=function()return {bindAction=function(k,f)bindings[k]=f end,activateTrigger=function()error('already readied')end}end
package.preload['openmw.camera']=function()return {getYaw=function()return 0 end,getPitch=function()return 0 end}end
package.preload['openmw.util']=function()return {vector3=V.new}end
package.preload['openmw.nearby']=function()return {castRay=function()return {hit=true}end}end
package.preload['scripts.astrabridge.terrain']=function()return {reset=function()end,observe=function()return {supported=false}end,
 probe=function(_,meters)return {distance=surfaceClear and meters*70 or 0,obstacle=not surfaceClear and 'geometry' or nil}end}end
package.preload['openmw.vfs']=function()return {}end
package.preload['openmw.markup']=function()return {}end
package.preload['openmw.interfaces']=function()return {Controls=direct and {overrideMovementControls=function(v)movementOverridden=v end} or nil,
 UI={MODE={Interface='Interface'},getMode=function()end,
    getWindowsForMode=function()return {Stats='Stats',Magic='Magic'}end}}end
package.preload['openmw.ui']=function()return {
    _astraProjectileParameters=blockedShot and function()return {supported=true,origin=V.new(0,0,0),speed_min=600,speed_max=1000,gravity=62.7,strength=1}end or nil,
    _astraPlayerState=function()return {animation_busy=shotBusy,submerged=submerged}end,
    _astraCombatInfo=function()return {weapon_info=ranged and {kind=ammo>0 and 'ranged' or 'unarmed',name=ammo>0 and 'Throwing star' or 'Fists',available=true} or nil,
        castable={kind='enchantment',name='Ring',available=charge>=4,
        unavailable_reason=charge<4 and 'insufficient_charge' or nil,cost=4,charge_current=charge}}end,
}end
package.preload['openmw.core']=function()return {
    isWorldPaused=function()return paused end,getRealTime=function()return now end,getSimulationTime=function()return aerialMode and simulationTime or now end,
    sendGlobalEvent=function(n,d)events[#events+1]={n,d}end,
    magic={enchantments={records={private_enchantment={effects={{effect={name='Heal'},range=0,duration=1,magnitudeMin=3,magnitudeMax=3,area=0}}}}}},
}end
package.preload['scripts.astrabridge.scene']=function()return {
    identity=function()return {details_visible=false}end,
    unitsPerMeter=70,fov=function()end,reset=function()end,pose=function()return {position=object.position,yaw=0,pitch=0,cell='private'}end,
    angle=function(v)return (v+math.pi)%(2*math.pi)-math.pi end,
    report=function()return {}end,orientation=function()return {}end,observe=function()return {objects={}}end,
    resolve=function(ref)if ref=='visible_enemy' then return {obj=enemy,center=V.new(0,1400,0),point=V.new(0,1400,0)}end end,
    track=function()return {obj=enemy,center=V.new(0,1400,0),point=V.new(0,1400,0)}end,
    lookAngles=function()aimCalls=aimCalls+1;return 0,0 end,combatAligned=function()return true end,
}end
local player=require('scripts.astrabridge.player')
local queuedUse,lastUse=false,false
local pauseEvents=0
local movingCasts=0
local function tick()
    now=now+.2
    local queue=events;events={}
    for _,event in ipairs(queue) do
        if event[1]=='AstraPause' then paused=true;pauseEvents=pauseEvents+1;player.eventHandlers.AstraPaused(event[2])end
        if event[1]=='AstraResume' then paused=false;player.eventHandlers.AstraResumed(event[2])end
    end
    if not paused and not modalPaused then
        simulationTime=simulationTime+.2
        local movement=movementOverridden and (object.controls.movement or 0) or bindings.MoveForward(.2,0)-bindings.MoveBackward(.2,0)
        local side=movementOverridden and (object.controls.sideMovement or 0) or bindings.MoveRight(.2,0)-bindings.MoveLeft(.2,0)
        local speed=movementOverridden and object.controls.run and 210 or 140
        object.position=V.new(object.position.x+side*speed*.2,object.position.y+movement*speed*.2,object.position.z)
        if object.controls.jump then jumpPulses=jumpPulses+1 end
        if aerialMode then
            if landingDamagePending then health=health-3;landingDamagePending=false end
            if object.controls.jump and object.position.z==0 and not denyJump then verticalVelocity=560 end
            if object.position.z>0 or verticalVelocity>0 then
                verticalVelocity=verticalVelocity-280*.2
                object.position=V.new(object.position.x,object.position.y,math.max(0,object.position.z+verticalVelocity*.2))
                if object.position.z==0 then verticalVelocity=0;landingDamagePending=true end
            end
        end
        local use=bindings.Use(.2,false)
        if ranged then
            -- Weapon use holds, then releases a projectile. An unrelated charge
            -- drain must never count as proof of ammunition expenditure.
            shotBusy=use or lastUse
            if lastUse and not use then
                shots=shots+1;charge=charge-1
                if not failShots then ammo=math.max(0,ammo-1) end
            end
            lastUse=use
        else
            if object.controls.use==1 then casts=casts+1;charge=charge-4;if movement~=0 then movingCasts=movingCasts+1 end end
            -- Stock playercontrols has an async action callback and emits Any for exactly one frame.
            object.controls.use=queuedUse and 1 or 0
            queuedUse=use and not lastUse;lastUse=use
        end
    end
    player.engineHandlers.onFrame((paused or modalPaused) and 0 or .2)
end
player.eventHandlers.AstraReset();for _=1,10 do tick()end
if aerialMode then
    local serial=0
    local function submit(op,args)
        serial=serial+1;data.response=nil;data.request={session='aerial',id=serial,op=op,args=args or {}}
    end
    local function finishCommand()
        for _=1,150 do tick();if data.response then break end end
        assert(data.response,'command must finish')
        return data.response.result,data.response.error
    end
    local function command(op,args) submit(op,args);return finishCommand() end
    local r=command('jump',{direction='forward',run=true})
    assert(r.reason=='landed' and r.aerial.took_off and r.aerial.landed)
    assert(r.aerial.peak_rise_m>4 and r.aerial.damage_taken==3 and jumpPulses==1)
    assert(object.position.y>100 and object.controls.movement==0 and not object.controls.jump)
    local stoppedAt=object.position
    for _=1,20 do tick() end
    assert((object.position-stoppedAt):length()==0)
    r=command('jump',{seconds=.4})
    assert(r.reason=='airborne' and r.aerial.took_off and not r.aerial.landed)
    assert(r.body.on_ground==false and r.body.air_state=='ascending')
    local _,err=command('jump',{})
    assert(err=='jump_requires_ground' and jumpPulses==2)
    r=command('air_move',{direction='right',seconds=.4})
    assert(r.reason=='duration' and r.aerial.started_airborne and not r.aerial.took_off and object.position.x>0)
    r=command('wait_until',{condition='landed',seconds=10})
    assert(r.reason=='condition_met' and r.aerial.landed and r.body.air_state=='grounded')
    _,err=command('air_move',{direction='forward'})
    assert(err=='airborne_required')
    denyJump=true
    r=command('jump',{})
    assert(r.reason=='jump_not_started' and not r.aerial.took_off)
    denyJump=false
    object.position=V.new(0,0,700);verticalVelocity=-100
    r=command('air_move',{direction='left',seconds=10})
    assert(r.reason=='landed' and r.aerial.started_airborne and not r.aerial.took_off)
    assert(object.position.x<0 and object.controls.sideMovement==0)
    object.position=V.new(0,0,700);verticalVelocity=0
    submit('air_move',{direction='right',seconds=20})
    for _=1,5 do tick() end
    data.cancel=true;r=finishCommand()
    assert(r.reason=='cancelled' and object.controls.sideMovement==0 and not object.controls.jump)
    require('openmw.ui')._astraUiSnapshot=function()return {revision='tutorial',modal=modalPaused,elements={}}end
    submit('air_move',{direction='forward',seconds=20})
    for _=1,3 do tick() end
    modalPaused=true;r=finishCommand()
    assert(r.reason=='ui_input_required' and r.aerial.started_airborne and object.controls.movement==0)
    print('Aerial helpers: one launch, directional steering, landing, no takeoff, cancellation and modal interruption')
    return
end
if arg[1]=='modal' or arg[1]=='modal_direct' then
    require('openmw.ui')._astraUiSnapshot=function()
        return {revision='tutorial',modal=modalPaused,elements={}}
    end
    for id,args in ipairs({{seconds=30,move=1,run=true},
                          {air=true,actions={{op='wait',seconds=20},{op='cast'}},max_seconds=30}}) do
        local op=id==1 and 'act' or 'chain'
        data.response=nil;data.request={session='adapter',id=id,op=op,args=args}
        local beforeCasts=casts
        for _=1,5 do tick()end
        assert(not data.response)
        modalPaused=true
        for _=1,10 do tick();if data.response then break end end
        assert(data.response and data.response.result.reason=='ui_input_required','modal must interrupt '..op)
        assert(paused and object.controls.movement==0 and object.controls.sideMovement==0 and object.controls.use==0)
        if op=='chain' then
            assert(data.response.result.completed_actions==0 and #data.response.result.steps==1 and casts==beforeCasts,
                'a modal must not execute the remaining chain steps')
        end
        modalPaused=false
        local stoppedAt=object.position
        for _=1,5 do tick()end
        assert((object.position-stoppedAt):length()==0)
    end
    print('Modal interrupts direct/legacy movement and combat chains without subsequent casts')
    return
end
if arg[1]=='sequence_guard' then
    data.request={session='adapter',id=1,op='act',args={seconds=50,move=1,_guard={health=50,stop_on_damage=true,deadline=now+100}}}
    local runningFrames=0
    for _=1,100 do
        if not paused then runningFrames=runningFrames+1;if runningFrames==3 then health=49 end end
        tick();if data.response then break end
    end
    assert(data.response and not data.response.error)
    assert(data.response.result.reason=='player_hurt' and data.response.result.elapsed<2 and paused,
        'damage inside a long act must pause immediately, not at the next sequence boundary')
    assert(object.controls.movement==0 and object.controls.sideMovement==0)
    print('Actual motor: sequence damage guard interrupts long act and clears input')
    return
end
if blockedShot then
    data.request={session='adapter',id=1,op='strike',args={ref='visible_enemy'}}
    for _=1,100 do tick();if data.response then break end end
    assert(data.response and not data.response.error)
    local result=data.response.result
    assert(result.reason=='shot_path_blocked' and not result.attempted and shots==0 and ammo==2,
        'a camera-visible target must not consume ammunition when the weapon trajectory meets a wall')
    assert(result.aim_assistance=='ballistic' and paused)
    return
end
if ranged then
    local before=pauseEvents
    data.request={session='adapter',id=1,op='chain',args={air=true,actions={{op='strike'},{op='strike'},{op='strike'}}}}
    for _=1,200 do tick();if data.response then break end end
    assert(data.response and not data.response.error)
    local result=data.response.result
    assert(result.reason=='weapon_changed' and result.completed_actions==2 and shots==2 and ammo==0,
        'depletion must stop the series before an accidental unarmed attack')
    assert(result.steps[1].resources.ammunition_change==-1 and result.steps[2].resources.ammunition_change==-1,
        'the last shot still counts when the empty weapon is automatically unequipped')
    assert(not result.steps[3].attempted and paused and pauseEvents==before+1)
    ammo=2;failShots=true;data.response=nil
    data.request={session='adapter',id=2,op='strike',args={air=true}}
    for _=1,100 do tick();if data.response then break end end
    result=data.response.result
    assert(result.reason=='shot_not_confirmed' and ammo==2 and shots==3,
        'animation and unrelated charge loss do not prove a projectile was fired')
    submerged=true;data.response=nil
    data.request={session='adapter',id=3,op='strike',args={air=true}}
    for _=1,100 do tick();if data.response then break end end
    assert(data.response.result.reason=='underwater_ranged_unavailable' and not data.response.result.attempted and ammo==2 and shots==3,
        'reject underwater ranged use before ammunition is consumed and discarded by the engine')
    print('Ranged adapter: exact ammo deltas, depletion guard, one pause and no false confirmation passed')
    return
end
local soloElapsed=0
for id=1,2 do
    data.response=nil;data.request={session='adapter',id=id,op='cast',args={}}
    for _=1,100 do tick();if data.response then break end end
    assert(data.response and not data.response.error)
    assert(data.response.result.reason=='completed','do not overwrite the stock one-frame casting pulse')
    assert(casts==id and charge==20-id*4,'one command must spend exactly one charge cost')
    assert(paused and object.controls.use==0)
    soloElapsed=soloElapsed+data.response.result.elapsed
end
local before=pauseEvents
data.response=nil;data.request={session='adapter',id=3,op='chain',args={actions={{op='cast'},{op='cast'},{op='cast'}}}}
for _=1,200 do tick();if data.response then break end end
assert(data.response and not data.response.error)
local result=data.response.result
assert(result.reason=='completed' and result.completed_actions==3 and #result.steps==3)
assert(result.elapsed<soloElapsed/2*3,'a continuous series reuses its confirmed release instead of inserting fresh-command idle time')
assert(casts==5 and charge==0,'the chain must perform exactly the requested three additional uses')
assert(pauseEvents==before+1,'there must be only one pause for the entire chain')
assert(paused and object.controls.use==0)
charge=8;before=pauseEvents
data.response=nil;data.request={session='adapter',id=4,op='chain',args={actions={{op='cast'},{op='cast'},{op='cast'}}}}
for _=1,200 do tick();if data.response then break end end
result=data.response.result
assert(result.reason=='insufficient_charge' and result.completed_actions==2 and #result.steps==3)
assert(not result.steps[3].attempted and charge==0 and casts==7 and pauseEvents==before+1)
charge=8
data.response=nil;data.request={session='adapter',id=5,op='chain',args={actions={{op='cast'}},max_seconds=.5}}
for _=1,100 do tick();if data.response then break end end
result=data.response.result
assert(result.reason=='chain_time_limit' and not result.steps[1].attempted and charge==8 and paused)
print('Real adapter preserves the delayed stock casting pulse at 5 simulation frames per second')

charge=8;before=pauseEvents
local previousCasts=casts
local start=object.position
local movingBefore=movingCasts
data.response=nil;data.request={session='adapter',id=6,op='chain',args={actions={{op='cast'},{op='cast'}},
 movement={direction='forward',meters=8},max_seconds=10}}
for _=1,200 do tick();if data.response then break end end
assert(data.response and not data.response.error)
result=data.response.result
assert(result.completed_actions==2 and result.reason=='completed')
assert(result.movement.reason=='maneuver_complete' and result.movement.travelled_m>=7.9)
assert(casts==previousCasts+2 and movingCasts==movingBefore+2,'casts must happen while moving, exactly once each')
assert(pauseEvents==before+1,'both lanes must share one final pause')
charge=8;surfaceClear=false;before=pauseEvents;previousCasts=casts
data.response=nil;data.request={session='adapter',id=7,op='chain',args={actions={{op='cast'}},movement={direction='forward',meters=2},max_seconds=8}}
for _=1,200 do tick();if data.response then break end end
result=data.response.result
assert(result.reason=='completed' and result.movement.reason=='maneuver_blocked')
assert(result.completed_actions==1 and casts==previousCasts+1 and charge==4,'healing finishes when movement is blocked')
assert(pauseEvents==before+1)
print('Concurrent movement and healing: overlap, no duplicate casts, independent completion and one pause passed')

charge=12;surfaceClear=true;before=pauseEvents;previousCasts=casts
local previousAim=aimCalls
data.response=nil;data.request={session='adapter',id=8,op='chain',args={ref='visible_enemy',actions={{op='cast'},{op='cast'},{op='cast'}},
 movement={direction='back',meters=.3,face_target=true},max_seconds=10}}
for _=1,200 do tick();if data.response then break end end
assert(data.response and not data.response.error)
result=data.response.result
assert(result.reason=='completed' and result.movement.reason=='maneuver_complete' and result.completed_actions==3)
assert(aimCalls-previousAim>15,'target tracking must continue during casts after the movement has finished')
assert(casts==previousCasts+3 and pauseEvents==before+1)
print('Lock continues after movement lane completion while healing finishes')

charge=16;health=50;before=pauseEvents;previousCasts=casts
data.response=nil;data.request={session='adapter',id=9,op='chain',args={actions={{op='cast'},{op='cast'},{op='cast'}},stop_health_pct=40}}
for _=1,200 do
    tick()
    if casts>previousCasts then health=15 end
    if data.response then break end
end
result=data.response.result
assert(result.reason=='health_low' and casts==previousCasts+1 and charge==12)
assert(paused and pauseEvents==before+1 and object.controls.use==0,'a health guard stops without repeating the cast')
charge=4;health=50;before=pauseEvents;previousCasts=casts
data.response=nil;data.request={session='adapter',id=10,op='chain',args={actions={{op='cast'}},movement={direction='forward',meters=8},max_seconds=10}}
local afterUse=0
for _=1,200 do
    tick()
    if casts>previousCasts then afterUse=afterUse+1 end
    if afterUse>=5 then playerDead=true;health=0 end
    if data.response then break end
end
assert(data.response.result.reason=='player_down' and pauseEvents==before+1,'death during a remaining movement lane is not completion')
print('Opt-in health stop and death while finishing movement passed')

playerDead=false;health=50;charge=8;before=pauseEvents;previousCasts=casts;previousAim=aimCalls
data.response=nil;data.request={session='adapter',id=11,op='chain',args={ref='visible_enemy',
 actions={{op='cast'},{op='wait',seconds=6},{op='cast'}},max_seconds=20}}
for _=1,200 do tick();if data.response then break end end
result=data.response.result
assert(result.reason=='completed' and result.completed_actions==3 and casts==previousCasts+2 and charge==0)
assert(result.steps[2].operation=='wait' and not result.steps[2].attempted and result.steps[2].elapsed>=6)
assert(pauseEvents==before+1 and aimCalls>previousAim+10,'stationary healing and waiting keep the view lock and share one pause')
if direct then
    assert(movementOverridden and bindings.MoveForward==nil,'stock movement must not overwrite the agent, while Use stays stock')
    data.response=nil;data.request={session='adapter',id=12,op='unlock',args={}}
    for _=1,100 do tick();if data.response then break end end
    data.response=nil;data.request={session='adapter',id=13,op='act',args={move=1,run=true,seconds=.6}}
    for _=1,100 do tick();if data.response then break end end
    local stoppedAt=object.position
    data.response=nil;data.request={session='adapter',id=14,op='chain',args={actions={{op='wait',seconds=1}}}}
    for _=1,100 do tick();if data.response then break end end
    assert((object.position-stoppedAt):length()<.001,'a stationary next action must not inherit movement from the preceding run')
    local oldJumps=jumpPulses
    data.response=nil;data.request={session='adapter',id=15,op='act',args={trigger='Jump',seconds=.6}}
    for _=1,100 do tick();if data.response then break end end
    assert(jumpPulses==oldJumps+1,'one Jump trigger must create exactly one normal jump pulse')
    assert(not object.controls.jump and object.controls.movement==0 and object.controls.sideMovement==0)
end

-- Independent cancellation retains the interrupted motor result and one pause.
playerDead=false;health=50;before=pauseEvents
data.response=nil;data.request={session='adapter',id=20,op='act',args={seconds=140,move=1}}
for _=1,15 do tick()end
assert(not data.response and not paused)
data.cancel=true
for _=1,15 do tick();if data.response then break end end
assert(data.response.result.reason=='cancelled' and data.response.result.elapsed>0)
assert(paused and pauseEvents==before+1 and not object.controls.sneak)
for id,condition in ipairs({'fatigue','animation','passage'}) do
    surfaceClear=true;shotBusy=false;data.response=nil
    data.request={session='adapter',id=20+id,op='wait_until',args={condition=condition,percent=100,seconds=10}}
    for _=1,20 do tick();if data.response then break end end
    assert(data.response and data.response.result.reason=='condition_met',condition)
end
surfaceClear=false;data.response=nil
data.request={session='adapter',id=24,op='wait_until',args={condition='passage',seconds=2}}
for _=1,40 do tick();if data.response then break end end
assert(data.response.result.reason=='condition_timeout' and paused)
local ui=require('openmw.ui');local opened=0
ui._astraRest=function()opened=opened+1;return true end
data.response=nil;data.request={session='adapter',id=25,op='trigger',args={name='Rest'}}
for _=1,20 do tick();if data.response then break end end
assert(opened==1 and data.response.result.reason=='ui_opened')
print('Interrupting long motor action, conditional waits and native Rest passed')

-- Tutorial scripts can revoke controls during a command; this is not a stuck route.
local playerType=require('openmw.types').Player
playerType.getControlSwitch=function()return true end
data.response=nil;data.request={session='adapter',id=26,op='act',args={move=1,seconds=15}}
for _=1,8 do tick()end
playerType.getControlSwitch=function()return false end
for _=1,20 do tick();if data.response then break end end
assert(data.response.result.reason=='player_controls_disabled' and paused)
data.response=nil;data.request={session='adapter',id=27,op='wait_until',args={condition='controls',seconds=10}}
for _=1,8 do tick()end
assert(not data.response,'disabled controls must not satisfy the wait')
playerType.getControlSwitch=function()return true end
for _=1,20 do tick();if data.response then break end end
assert(data.response.result.reason=='condition_met' and paused)

-- The pause handshake replaces the pending motor; preserve the interacted
-- door's handle so its visible state change can still confirm the outcome.
data.response=nil;data.request={session='adapter',id=28,op='unlock',args={}}
for _=1,20 do tick();if data.response then break end end
local scene=require('scripts.astrabridge.scene')
local types=require('openmw.types')
local doorState,activations=0,0
local door={isValid=function()return true end}
local goal={obj=door,center=V.new(0,100,0),point=V.new(0,100,0)}
types.Door={STATE={Opening=1,Closing=2},objectIsInstance=function(o)return o==door end,
    getDoorState=function()return doorState end,isOpen=function()return false end}
scene.resolve=function(ref)if ref=='visible_door' then return goal end end
scene.reach=function()return true end
scene.aimedAt=function()return true end
scene.crosshair=function()return true end
for _,name in ipairs({'Dialogue','Container','Book','Scroll'}) do require('openmw.interfaces').UI.MODE[name]=name end
ui._astraActivate=function(expected)
    assert(expected==door,'targeted activation must carry the expected object')
    activations=activations+1;doorState=1;return true
end
data.response=nil;data.request={session='adapter',id=29,op='interact',args={ref='visible_door'}}
for _=1,40 do tick();if data.response then break end end
assert(data.response and not data.response.error)
assert(data.response.result.outcome=='door_opening' and activations==1 and paused,
    'a visible door change must survive pausing, without repeating activation')

-- OnActivate can show a tutorial while Lua UI mode remains Gameplay. The
-- interactionSubmitted timer must not wait forever for paused simulation dt.
ui._astraUiSnapshot=function()return {revision='tutorial',modal=modalPaused,elements={}}end
ui._astraActivate=function(expected)
    assert(expected==door);activations=activations+1;modalPaused=true;return true
end
data.response=nil;data.request={session='adapter',id=30,op='interact',args={ref='visible_door',approach=true}}
for _=1,40 do tick();if data.response then break end end
assert(data.response and data.response.result.reason=='ui_input_required' and paused)
assert(activations==2 and data.response.result.outcome=='activation_sent','keep activation evidence without repeating it')
print('Native activation modal interrupts confirmation waiting with Gameplay UI mode and zero dt')
