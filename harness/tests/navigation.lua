package.path='mod/?.lua;'..package.path
math.atan2=math.atan2 or math.atan
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z},V)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
function V.__add(a,b)return V.new(a.x+b.x,a.y+b.y,a.z+b.z)end
function V.__mul(a,b)return V.new(a.x*b,a.y*b,a.z*b)end
function V:length()return math.sqrt(self.x^2+self.y^2+self.z^2)end
local self={position=V.new(0,0,0)}
local calls=0
local waterWalking=false
package.preload['openmw.core']=function()return {magic={EFFECT_TYPE={WaterWalking='ww'}}}end
local nearby={NAVIGATOR_FLAGS={Walk=1,Swim=2,OpenDoor=4,UsePathgrid=8},FIND_PATH_STATUS={Success=1,PartialPath=2}}
nearby.findPath=function(source,dest,options)
    calls=calls+1
    assert(options.includeFlags==11,'may route into water but never through closed doors')
    assert(options.agentBounds=='player_bounds')
    return 1,{V.new(0,0,0),V.new(0,0,140),V.new(140,0,140),dest}
end
package.preload['openmw.nearby']=function()return nearby end
package.preload['openmw.self']=function()return self end
package.preload['openmw.util']=function()return {vector3=V.new}end
package.preload['openmw.types']=function()return {Actor={objectIsInstance=function()return true end,getPathfindingAgentBounds=function()return 'player_bounds'end,
    activeEffects=function()return {getEffect=function()return {magnitude=waterWalking and 1 or 0}end}end}}end
local N=require('scripts.astrabridge.navigation')
local target={position=V.new(280,0,140)}
local goal={obj=target}
local n=N.new(goal)
assert(calls==1)
assert(N.step(n,goal,.1).z==140,'a point on the floor above must not be skipped')
self.position=V.new(0,0,140)
assert(N.step(n,goal,.1).x==140)
target.position=V.new(500,0,140)
N.step(n,nil,2)
assert(calls==1 and n.goal.x==280,'hidden moving targets must not be tracked by their world position')
N.step(n,goal,1)
assert(calls==2 and n.goal.x==500,'visible moving targets should update the route')
local r=N.report(n)
assert(r.status=='planned' and r.remaining_m>0 and r.path==nil and r.goal==nil)
local coarse={goal=self.position+V.new(60,0,0),arrivalTolerance=63}
assert(N.reached(coarse),'a passage step can stop nearby without turning back to a tiny target')
coarse.arrivalTolerance=25;assert(not N.reached(coarse),'a recorded waypoint retains precise arrival')
coarse.arrivalTolerance=63;coarse.goal=self.position+V.new(0,0,140)
assert(not N.reached(coarse),'coarse XY arrival never accepts a different floor')
nearby.findPath=function()return 99,{}end
assert(N.new(goal).status=='no_path')
local near=V.new(self.position.x+30,self.position.y,self.position.z)
assert(N.moveFraction(near,.2,false)<1,'low FPS must brake before a nearby waypoint')
assert(N.moveFraction(near,.02,false)==1,'distant relative to a frame needs no slowdown')
-- Both sampled positions miss the radius, but the actor actually crossed it.
local fast={path={V.new(140,0,140),V.new(280,0,140)},index=1,sincePlan=0,previousPosition=V.new(100,0,140)}
self.position=V.new(180,0,140)
assert(N.step(fast,nil,.2).x==280,'do not turn back after crossing an intermediate waypoint between frames')
fast={path={V.new(140,0,280),V.new(280,0,280)},index=1,sincePlan=0,previousPosition=V.new(100,0,140)}
assert(N.step(fast,nil,.2).x==140,'swept movement must still respect the floor')
local frozen=n.goal
target.position=V.new(999,999,999)
nearby.findPath=function(_,dest)
    assert(dest==frozen,'recovery must not re-read a hidden moving actor position')
    return 1,{self.position,dest}
end
N.begin(n);n.blockedBy='actor'
assert(N.recover(n,0))
assert(N.step(n,nil,.2)==self.position and n.status=='waiting')
N.step(n,nil,.6)
package.preload['scripts.astrabridge.terrain']=function()return {
    contact=function()return {kind='actor'}end,
    walkLine=function()return nil end,
    probe=function()return {point=V.new(70,0,140),distance=70,vertical=0}end,
}end
assert(N.clearance(n,V.new(100,0,140))==0 and n.blockedBy=='actor')
assert(not N.recover(n,0) and not n.detour,'never sidestep when the second leg is still blocked by an actor')
n.attempts=4
assert(not N.recover(n,0),'recovery must terminate rather than loop forever')
assert(N.report(n).recovery_count==2)
local terrain=require('scripts.astrabridge.terrain')
coarse.goal=self.position+V.new(60,0,0);nearby.castNavigationRay=function(_,goal)return goal end
terrain.contact=function()return nil end
assert(N.canFinish(coarse))
terrain.contact=function()return {kind='geometry'}end
assert(not N.canFinish(coarse),'nearby on the other side of a wall is not arrival')
terrain.contact=function()return nil end
nearby.castNavigationRay=function()return self.position end
assert(not N.canFinish(coarse),'nearby across a disconnected floor is not arrival')
local short={goal=V.new(700,0,0),path={V.new(680,0,0)},arrivalTolerance=25,index=1,sincePlan=0}
self.position=V.new(660,0,0)
assert(N.step(short,nil,.1),'do not finish at the edge of a waypoint radius if that remains outside the requested goal radius')
self.position=V.new(676,0,0);assert(N.reached(short))
local wrongHeight={goal=V.new(676,0,-40),path={V.new(676,0,-40)},index=1,sincePlan=0}
assert(N.step(wrongHeight,nil,.1)==nil and wrongHeight.status=='height_mismatch',
    'a final point directly under the feet must stop with an explanation, not rotate indefinitely')
for _,dt in ipairs({.05,.1,.2,.3}) do
    self.position=V.new(0,0,0)
    local goal=V.new(700,0,0)
    local route={goal=goal,path={goal},index=1,sincePlan=0}
    local queue={0,0};local stopped=false
    for _=1,500 do
        if N.reached(route) then
            for _=1,2 do
                table.insert(queue,0);self.position=self.position+V.new(table.remove(queue,1)*200*dt,0,0)
            end
            stopped=true;break
        end
        N.step(route,nil,dt)
        table.insert(queue,N.moveFraction(goal,dt,false,route))
        self.position=self.position+V.new(table.remove(queue,1)*200*dt,0,0)
    end
    assert(stopped and N.reached(route),'the endpoint must remain reached after two queued input frames settle')
end
print('Private navigation: floors, visible target updates, no water/door bypass, no coordinate export passed')
waterWalking=true;self.cell={waterLevel=0};self.position=V.new(0,0,0)
nearby.findPath=function(source,dest,options)
    assert(options.includeFlags==11 and dest.z==0,'water walking must route at the surface')
    return 1,{V.new(0,0,-80),V.new(70,0,-80),V.new(140,0,-80)}
end
local waterRoute=N.new({groundPoint=V.new(140,0,-80)})
assert(waterRoute.waterWalking and waterRoute.goal.z==0)
for _,point in ipairs(waterRoute.path)do assert(point.z==0)end
local mobility=require('scripts.astrabridge.mobility')
assert(mobility.surface(V.new(0,0,120)).z==120,'a dry bridge must stay above water')
waterWalking=false
assert(mobility.flags(nearby.NAVIGATOR_FLAGS)==3 and mobility.surface(V.new(0,0,-80)).z==-80)

-- Recorded travel is a fallback to native navigation, not a replacement.
self.cell=nil;self.position=V.new(0,0,0)
local trail={self.position,V.new(0,70,0),V.new(70,70,0)}
local floorGoal={groundPoint=trail[#trail],recordedPath=trail}
terrain.contact=function()return nil end
nearby.findPath=function(_,goal)return nearby.FIND_PATH_STATUS.Success,{self.position,goal}end
local native=N.new(floorGoal)
assert(not native.recorded and N.report(native).source=='navmesh')
nearby.findPath=function()return nearby.FIND_PATH_STATUS.PartialPath,{self.position,V.new(70,70,-256)}end
local fallback=N.new(floorGoal)
assert(fallback.recorded and fallback.path==trail and N.report(fallback).reason=='incomplete_navmesh')
local wrongFloor=N.new({groundPoint=trail[#trail]})
assert(N.step(wrongFloor,nil,.1)==nil and wrongFloor.status=='endpoint_mismatch',
    'a partial path to the wrong floor must not move the player towards its endpoint')
nearby.findPath=function(_,goal)return nearby.FIND_PATH_STATUS.Success,{self.position,goal}end
terrain.contact=function()return {kind='door'}end
assert(N.new(floorGoal).recorded,'an opened door leaf can obstruct a nominally successful native path')
N.begin(fallback);fallback.blockedBy='door'
assert(not N.recover(fallback,0),'never replay a recorded path blindly through a now closed door')

-- A moving actor: wait, then use a clear two-leg local detour and rejoin the
-- route. Preserve the recorded route and re-check it during normal movement.
local detourPoint=V.new(77,0,0)
terrain.probe=function()return {point=detourPoint,distance=77,vertical=0}end
terrain.contact=function(a,b)
    if a~=detourPoint then return {kind='actor'}end
end
terrain.walkLine=function(a,b)return not terrain.contact(a,b) and {a,b} or nil end
local crowded={goal=V.new(0,210,0),path={V.new(0,70,0),V.new(0,140,0),V.new(0,210,0)},
    index=1,recorded=true,status='recorded',pathStatus='recorded',sincePlan=0,replans=0}
N.begin(crowded);crowded.blockedBy='actor'
assert(N.recover(crowded,0) and crowded.waitRemaining)
N.step(crowded,nil,.8)
assert(N.recover(crowded,0) and crowded.detour==detourPoint and crowded.rejoinIndex)
self.position=detourPoint
local join=N.step(crowded,nil,.1)
assert(join and crowded.detour==join and crowded.recorded)
self.position=join
assert(N.step(crowded,nil,.1) and not crowded.detour and crowded.recorded)
crowded.attempts=4
assert(not N.recover(crowded,0),'dynamic recovery remains bounded')

-- Static door origin is inside a wall, but an activation standing point exists.
self.position=V.new(0,0,0)
require('openmw.types').Actor.objectIsInstance=function()return false end
require('openmw.core').getGMST=function()return 140 end
local door={};local goal={obj=door,center=V.new(0,350,70),half=V.new(20,20,70)}
nearby.castRay=function()return {hit=true,hitObject=door}end
nearby.findPath=function(_,dest)
    if dest.x==0 and dest.y==350 then return 99,{} end
    return 1,{self.position,dest}
end
local plan=N.new(goal)
assert(plan.standingPoint and plan.status=='planned' and plan.goal.y==350,
    'a door inside a wall needs a reachable activation standing point')
nearby.castRay=function()return {hit=true,hitObject={}}end
assert(not N.new(goal).standingPoint,'a standing point behind intervening geometry cannot activate the door')

-- A coarse native endpoint must not strand the actor just short of its known point.
self.position=V.new(0,0,0)
local terrain=require('scripts.astrabridge.terrain')
terrain.walkLine=function(from,to)return {from,to}end
local endpoint={goal=V.new(45,0,0),path={V.new(10,0,0)},index=1,sincePlan=0,lastGoal={groundPoint=V.new(45,0,0)}}
assert(N.step(endpoint,nil,.1).x==45 and endpoint.localPath)
terrain.walkLine=function()return nil end
endpoint={goal=V.new(45,0,0),path={V.new(10,0,0)},index=1,sincePlan=0,lastGoal={groundPoint=V.new(45,0,0)}}
assert(N.step(endpoint,nil,.1)==nil,'do not finish a short gap without safe floor support')
