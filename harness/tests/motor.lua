package.path='mod/?.lua;'..package.path
local now,simulation,paused,yaw,pitch=0,0,true,0,0
local visible,dead=true,false
local playerDead=false
local corpseSettled=false
local inReach=true
local health=50
local data,events,bindings={},{},{}
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z},V)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
function V.__add(a,b)return V.new(a.x+b.x,a.y+b.y,a.z+b.z)end
function V:length()return math.sqrt(self.x^2+self.y^2+self.z^2)end
local actor={npc=true,type={record=function()return {name='Walking NPC'}end}}
local self={controls={},ATTACK_TYPE={NoAttack=0,Any=1},position=V.new(0,0,0),cell={id='private_cell',displayName='Room'},object={}}
local bus={get=function(_,k)return data[k]end,getCopy=function(_,k)return data[k]end,set=function(_,k,v)data[k]=v end}
local function angle(x)return (x+math.pi)%(2*math.pi)-math.pi end
package.preload['openmw.storage']=function()return {playerSection=function()return bus end}end
package.preload['openmw.camera']=function()return {getYaw=function()return yaw end,getPitch=function()return pitch end}end
package.preload['openmw.self']=function()return self end
package.preload['openmw.ui']=function()return {}end
package.preload['openmw.util']=function()return {vector3=V.new}end
package.preload['openmw.vfs']=function()return {}end
package.preload['openmw.markup']=function()return {}end
package.preload['openmw.async']=function()return {callback=function(_,f)return f end}end
package.preload['openmw.input']=function()return {bindAction=function(k,f)bindings[k]=f end,activateTrigger=function()end}end
package.preload['openmw.interfaces']=function()return {UI={MODE={Interface='Interface'},getMode=function()return nil end,getWindowsForMode=function()return {}end}}end
package.preload['openmw.types']=function()return {
    Actor={stats={dynamic={health=function()return {current=health}end}},objectIsInstance=function(o)return o.npc end,isDead=function(o)return o==actor and dead or o==self and playerDead end},
    Player={CONTROL_SWITCH={Controls=1,Looking=2},getControlSwitch=function()return true end,isCharGenFinished=function()return true end}
}end
package.preload['openmw.core']=function()return {isWorldPaused=function()return paused end,getRealTime=function()return now end,
    getGameTime=function()return 0 end, getSimulationTime=function()return simulation end,
    sendGlobalEvent=function(n,d)events[#events+1]={n,d}end}end
package.preload['scripts.astrabridge.scene']=function()return {
    unitsPerMeter=70,angle=angle,reset=function()end,fov=function()end,
    pose=function()return {yaw=yaw,pitch=pitch,position=self.position,cell=self.cell.id}end,
    report=function(s)return {moved_m=(self.position-s.position):length()/70,turned_deg=math.deg(angle(yaw-s.yaw))}end,
    resolve=function(ref)if visible and ref=='visible_test' then return {obj=actor}end end,
    lookAngles=function()return simulation*.2,0 end,reach=function()return inReach end,crosshair=function()return true end,
    lootReady=function()if dead then return corpseSettled end end,
    aimedAt=function()return math.abs(angle(yaw-simulation*.2))<.02 end,
    orientation=function()return {heading_deg=math.deg(yaw)}end,observe=function()return {objects={}}end,
}end
package.preload['scripts.astrabridge.navigation']=function()return {
    new=function(g)return {path={},status='path_end',cell=self.cell.id,movingTarget=true,lastGoal=g}end,
    step=function()return nil end,report=function()return {status='path_end',remaining_m=0,replans=1}end,
}end
local player=require('scripts.astrabridge.player')
local attackFrames,lastAttack,pauseEvents=0,false,0
local function tick()
    now=now+.02
    local queue=events;events={}
    for _,event in ipairs(queue)do
        if event[1]=='AstraPause' then paused=true;pauseEvents=pauseEvents+1;player.eventHandlers.AstraPaused(event[2])end
        if event[1]=='AstraResume' then paused=false;player.eventHandlers.AstraResumed(event[2])end
    end
    if not paused then
        simulation=simulation+.02
        yaw=yaw+(self.controls.yawChange or 0);pitch=pitch+(self.controls.pitchChange or 0)
        local f=bindings.MoveForward(.02,0)-bindings.MoveBackward(.02,0)
        self.position=self.position+V.new(math.sin(yaw)*f,math.cos(yaw)*f,0)
        lastAttack=bindings.Use(.02,false)
        if lastAttack then attackFrames=attackFrames+1 end
    end
    self.controls.yawChange=0;self.controls.pitchChange=0
    player.engineHandlers.onFrame(paused and 0 or .02)
end
player.eventHandlers.AstraReset();for _=1,10 do tick()end
local id=0
local function command(op,args,during)
    id=id+1;data.response=nil;data.request={session='motor',id=id,op=op,args=args or {}}
    for n=1,10000 do
        if during then during(n)end
        tick();if data.response then return data.response end
    end
    error('no reply')
end
-- Cross the former input cap and every fixed transport/watchdog duration.
local pausesBefore=pauseEvents
local long=command('act',{seconds=140,move=1})
assert(not long.error and long.result.reason=='duration' and long.result.elapsed>=140)
assert(long.result.motion.moved_m>90 and paused and self.controls.movement==0)
assert(pauseEvents==pausesBefore+1,'a long action must have only its final pause')
pausesBefore=pauseEvents
long=command('track',{ref='visible_test',seconds=140})
assert(not long.error and long.result.reason=='tracked' and long.result.elapsed>=140)
assert(pauseEvents==pausesBefore+1 and paused,'long tracking must not pause at three seconds')
local r=command('lock',{ref='visible_test'});assert(not r.error and paused)
r=command('act',{seconds=1,move=1,attack=true})
assert(not r.error and paused and attackFrames>0)
assert(not lastAttack and r.result.released,'release must reach a simulation frame before pause')
assert(math.abs(angle(yaw-simulation*.2))<.025,'lock must follow a moving target')
local o=command('observe').result
assert(o.target_lock.status=='locked' and o.target_lock.ref=='visible_test','lock must survive commands')
r=command('act',{seconds=.8,attack=true},function(n)
    if n==15 then visible=false elseif n==20 then visible=true end
end)
assert(not r.error and r.result.reason=='duration','a brief visibility miss should reacquire the same target')
assert(command('observe').result.target_lock.status=='locked')
r=command('act',{seconds=2,attack=true},function(n)if n==15 then visible=false end end)
assert(not r.error and r.result.reason=='target_lost' and paused)
assert(self.controls.use==0,'attack must be released on lost target')
assert(command('observe').result.target_lock.status=='lost')
assert(command('act',{seconds=.5}).error=='target_not_visible')
visible=true
assert(not command('lock',{ref='visible_test'}).error)
r=command('act',{seconds=1,attack=true},function(n)if n==15 then dead=true end end)
assert(r.result.reason=='target_down' and self.controls.use==0)
assert(command('act',{seconds=.5,attack=true}).error=='invalid_lock_target')
assert(not command('unlock').error)
assert(command('observe').result.target_lock.status=='unlocked')
local waited=0
r=command('focus',{ref='visible_test',wait_ready=true},function(n)waited=n;if n==25 then corpseSettled=true end end)
assert(r.result.reason=='focused' and waited>=25,'interaction focus must wait for the visible death animation')
inReach=false
local before=self.position
r=command('approach',{ref='visible_test'})
assert(r.result.reason=='path_end_out_of_reach' and paused)
assert((self.position-before):length()==0,'do not walk blindly after the navigation path has ended')
inReach=true
local previousYaw=yaw
r=command('approach',{ref='visible_test'})
assert(r.result.reason=='within_reach' and yaw==previousYaw,'approach must not aim at the target after arrival')
r=command('act',{seconds=1},function(n)if n==15 then yaw=.7;pitch=.2 end end)
assert(r.result.reason=='duration' and yaw==.7 and pitch==.2,'a wait without an explicit turn must not restore a heading')
r=command('act',{seconds=2,move=1,yaw=90},function(n)
    if n==15 then self.cell={id='another_private_room',displayName='New room'};yaw=-1.2 end
end)
assert(r.result.reason=='location_changed' and paused,'door transition must stop the previous action')
assert(math.abs(yaw+1.2)<.1,'arrival heading must not be turned back towards the old room')
assert(self.controls.movement==0 and self.controls.yawChange==0)
print('Persistent moving-target lock, occlusion stop and attack release passed')

health=50;dead=false
r=command('move_local',{forward_m=3},function(n)if n==15 then health=49 end end)
assert(r.result.reason=='player_hurt' and r.result.damage_taken==1 and paused,'ordinary navigation must report incoming damage promptly')
health=50
r=command('move_local',{forward_m=.5,under_fire=true},function(n)if n==15 then health=49 end end)
assert(r.result.reason=='arrived','explicit under-fire movement must not pause on every hit')
r=command('look',{heading_deg=270,pitch_deg=-60})
assert(r.result.reason=='duration' and math.abs(angle(yaw-math.rad(270)))<.01 and math.abs(pitch-math.rad(-60))<.01)
r=command('look',{pitch_deg=60})
assert(math.abs(angle(yaw-math.rad(270)))<.01 and math.abs(pitch-math.rad(60))<.01,'absolute vertical look preserves unspecified heading')
r=command('act',{seconds=1},function(n)if n==15 then playerDead=true end end)
assert(r.result.reason=='player_down' and paused,'death interrupts ordinary timed input as well as combat')
assert(not data.can_save,'a dead character is not a valid save state')
