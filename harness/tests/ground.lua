package.path='mod/?.lua;'..package.path
math.atan2=math.atan2 or math.atan
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z or 0},V)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
function V.__add(a,b)return V.new(a.x+b.x,a.y+b.y,a.z+b.z)end
function V.__mul(a,b)return V.new(a.x*b,a.y*b,a.z*b)end
function V:length()return math.sqrt(self.x^2+self.y^2+self.z^2)end
function V:dot(o)return self.x*o.x+self.y*o.y+self.z*o.z end
local self={position=V.new(10000,20000,1000),cell={id='PRIVATE_CELL'},object={}}
local calls,mode,clock=0,'floor',0
local playing=true
local projected
local wall=false
package.preload['scripts.astrabridge.terrain']=function()return {contact=function(_,_,centerOnly)assert(centerOnly);return wall and {kind='geometry'} or nil end}end
package.preload['openmw.animation']=function()return {BONE_GROUP={LowerBody=1,Torso=2},
    getActiveGroup=function()return 'death1'end,isPlaying=function()return playing end}end
local nearby={findPath=function()end}
nearby.castRenderingRay=function()
    calls=calls+1
    if mode=='nothing' then return {hit=false}end
    local row=math.floor((calls-1)/5);local col=(calls-1)%5
    return {hit=true,hitPos=self.position+V.new((col-2)*100,(5-row)*200,row<2 and -210 or 0),
        hitNormal=mode=='wall' and V.new(1,0,.2) or V.new(0,0,1),hitObject=mode=='actor' and {actor=true} or mode=='item' and {item=true} or nil}
end
package.preload['openmw.self']=function()return self end
package.preload['openmw.nearby']=function()return nearby end
package.preload['openmw.camera']=function()return {getYaw=function()return 0 end,getPosition=function()return self.position end,
    viewportToWorldVector=function()return V.new(0,1,0)end,
    worldToViewportVector=function(p)projected=p;return {x=777,y=888}end}end
package.preload['openmw.ui']=function()return {screenSize=function()return {x=1000,y=1000}end}end
package.preload['openmw.util']=function()return {vector3=V.new,vector2=V.new}end
package.preload['openmw.core']=function()return {getSimulationTime=function()return clock end}end
package.preload['openmw.types']=function()return {Actor={isDead=function(o)return o.dead end,objectIsInstance=function(o)return o.actor end,getPathfindingAgentBounds=function()return {}end},
    Item={objectIsInstance=function(o)return o.item end}}end
package.preload['openmw.vfs']=function()return {}end
package.preload['openmw.markup']=function()return {}end
package.preload['scripts.astrabridge.navigation']=function()return {
    new=function(g)return g end,report=function()return {status='planned',remaining_m=5}end}end
local S=require('scripts.astrabridge.scene');S.reset('public')
local originalGroundPoint=S.groundPoint
assert(S.lootReady({obj={actor=true,dead=true}})==false)
playing=false;assert(S.lootReady({obj={actor=true,dead=true}})==true)
assert(S.lootReady({obj={actor=true,dead=false}})==nil)
for _,value in ipairs({'wall','actor','item','nothing'}) do
    mode=value;assert(S.groundPoint(100,500)==nil,'only rendered floor surfaces can be suggested')
end
mode='floor';calls=0
local targets=S.groundTargets();assert(calls==25 and #targets>0 and #targets<=9)
local lower=false
for _,g in ipairs(targets)do lower=lower or g.height_change_m< -1;assert(g.navigation.status=='planned')end
assert(lower,'visible lower landings must survive sampling')
local ref=targets[1].ref;assert(S.resolveGround(ref))
clock=4;assert(not S.resolveGround(ref),'old floor selections expire')
clock=0;self.position=self.position+V.new(40,0,0);assert(not S.resolveGround(ref))
mode='nothing';assert(#S.groundTargets()==0,'never substitute an unseen navigation point for a missed rendering ray')
local encoded=require('scripts.astrabridge.protocol').encode({ground_targets=targets})
assert(not encoded:find('PRIVATE') and not encoded:find('10000') and not encoded:find('"point":',1,true))
local raw=self.position+V.new(100,300,0)
local visibleEndpoint=true
S.groundPoint=function(x,y)
    if x==777 and y==888 then return visibleEndpoint and projected or nil end
    return raw
end
local offset=V.new(35,0,0)
local treadHeight=0
nearby.castRay=function(from)
    return {hit=true,hitNormal={z=1},hitPos=V.new(from.x,from.y,raw.z+treadHeight)}
end
local N=require('scripts.astrabridge.navigation')
N.new=function(g)return {goal=g.groundPoint,path={self.position,g.groundPoint+offset},status='planned'}end
N.report=function(n)return {status=n.status}end
targets=S.groundTargets();assert(#targets==1 and targets[1].target_adjustment_m==.5 and targets[1].navigation.status=='planned')
assert(S.resolveGround(targets[1].ref).x==raw.x+35,'the visible reachable point is the actual walk goal')
offset=V.new(10,0,0);targets=S.groundTargets();assert(targets[1].target_adjustment_m==.14,'small endpoint gaps also need a consistent walk target')
offset=V.new(35,0,0)
treadHeight=40;targets=S.groundTargets()
assert(S.resolveGround(targets[1].ref).z==raw.z+40,'walk targets must use the physical stair surface, not the lower navmesh Z')
treadHeight=0
visibleEndpoint=false;targets=S.groundTargets()
assert(targets[1].target_adjustment_m==0 and targets[1].navigation.status=='partial','do not suggest a hidden corrected endpoint')
visibleEndpoint=true;wall=true;targets=S.groundTargets()
assert(targets[1].target_adjustment_m==0,'never snap through a wall')
wall=false;offset=V.new(0,0,140);targets=S.groundTargets()
assert(targets[1].target_adjustment_m==0,'never snap to another floor')
print('Visible floor suggestions: bounded rendering rays, lower floors, no walls/actors/items, stale handles and no private coordinates passed')
require('scripts.astrabridge.mobility').waterLevel=function()return 0 end
self.position=V.new(0,0,100)
require('openmw.camera').viewportToWorldVector=function()return V.new(0,0,-1)end
nearby.castRenderingRay=function()return {hit=true,hitPos=V.new(0,0,-100),hitNormal=V.new(0,0,1)}end
assert(originalGroundPoint(100,500).z==0,'water walking chooses the visible water surface, not the bottom')
nearby.castRenderingRay=function()return {hit=true,hitPos=V.new(0,0,50),hitNormal=V.new(1,0,.2)}end
assert(originalGroundPoint(100,500)==nil,'water must not be selected through a nearer wall')
nearby.castRenderingRay=function()return {hit=true,hitPos=V.new(0,0,50),hitNormal=V.new(0,0,1)}end
assert(originalGroundPoint(100,500).z==50,'a bridge above the water remains the selected surface')

-- Replay the rope-bridge seam: rendering hits a vertical board edge while
-- the same object's walkable collision surface is only 5.5 units away.
require('scripts.astrabridge.mobility').waterLevel=function()return nil end
self.position=V.new(0,0,0)
local bridge={id='bridge_instance'}
local visual={hit=true,hitObject=bridge,hitPos=V.new(100,100,0),hitNormal=V.new(-.938937,.342887,-.028742)}
local support={hit=true,hitObject=bridge,hitPos=visual.hitPos+V.new(-4.336,1.344,3.112),hitNormal=V.new(-.018299,.005661,.999817)}
local supportCalls=0
nearby.castRenderingRay=function()return visual end
nearby.castRay=function(_,_,options)
    assert(options.ignore==self.object);supportCalls=supportCalls+1;return support
end
assert(originalGroundPoint(500,500)==support.hitPos,'a visible plank seam must resolve to nearby physical support')
S.groundPoint=originalGroundPoint
N.new=function(g)return g end;N.report=function()return {status='planned'}end
targets=S.groundTargets()
assert(#targets==1 and S.resolveGround(targets[1].ref)==support.hitPos,'ground and pixel walking must share the seam correction')

local savedSupport=support.hitPos
support.hitPos=visual.hitPos+V.new(0,0,9)
assert(not originalGroundPoint(500,500),'do not select a remote surface behind visible geometry')
support.hitPos=savedSupport;support.hitObject={id=bridge.id}
assert(not originalGroundPoint(500,500),'support must belong to the same instance, not just the same record or label')
support.hitObject=bridge;support.hitNormal=V.new(1,0,0)
assert(not originalGroundPoint(500,500),'a railing remains a wall in collision geometry')
support.hitNormal=V.new(0,0,0)
assert(not originalGroundPoint(500,500),'a degenerate collision normal is not floor support')
support.hitNormal=nil
assert(not originalGroundPoint(500,500))
support.hitNormal=V.new(0,0,1);support.hit=false
assert(not originalGroundPoint(500,500),'a visual board edge alone is not proof of support')
support.hit=true
for _,field in ipairs({'actor','item'}) do
    bridge[field]=true;local before=supportCalls
    assert(not originalGroundPoint(500,500) and supportCalls==before,'do not reinterpret an actor or item as ground')
    bridge[field]=nil
end
visual.hit=false;local before=supportCalls
assert(not originalGroundPoint(500,500) and supportCalls==before,'a collision surface hidden behind a rendering miss is not a visible target')
visual.hit=true
for _,scale in ipairs({.1,1,10}) do
    visual.hitNormal=V.new(0,0,scale);local before=supportCalls
    assert(originalGroundPoint(500,500)==visual.hitPos and supportCalls==before,'flat visible floors are invariant under model scaling and need no extra ray')
    visual.hitNormal=V.new(1,0,.2)*scale;support.hitNormal=V.new(1,0,.2)
    assert(not originalGroundPoint(500,500),'steep slopes remain rejected at every model scale')
end
print('Bridge seams use nearby support on the same instance; scaling, railings, occlusion and visible ground targets passed')
