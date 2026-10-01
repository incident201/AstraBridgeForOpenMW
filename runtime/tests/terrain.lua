package.path='mod/?.lua;'..package.path
math.atan2=math.atan2 or math.atan
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z or 0},V)end
function V.__add(a,b)return V.new(a.x+b.x,a.y+b.y,a.z+b.z)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
function V.__mul(a,b)return V.new(a.x*b,a.y*b,a.z*b)end
function V:length()return math.sqrt(self.x^2+self.y^2+self.z^2)end
local self={position=V.new(0,0,0),cell={id='private_room'},object={}}
local yaw,clock,mode=0,0,'floor'
local calls=0
local hidden={npc=true,id='private_actor',name='Unseen guard'}
local nearby={NAVIGATOR_FLAGS={Walk=1}}
nearby.castNavigationRay=function(from,to,opts)
 calls=calls+1;assert(opts.includeFlags==1)
 if mode=='missing' then return nil end
 if mode=='wall' and to.y>100 then return V.new(to.x,100,0)end
 if mode=='stairs' then return V.new(to.x,to.y,-to.y*.5)end
 return to
end
nearby.castRay=function(a,b,opts)
 local skipped=type(opts.ignore)=='table' and opts.ignore[1]==self.object and opts.ignore[2]==hidden
 assert(opts.ignore==self.object or skipped)
 if mode=='corpse' or mode=='corpse_wall' then
  if not skipped then return {hit=true,hitObject=hidden,hitPos=a+(b-a)*.2}end
  if mode=='corpse_wall' then return {hit=true,hitPos=a+(b-a)*.8}end
 end
 if mode=='actor' and a.y<170 and b.y>=170 and math.abs(b.x)<30 then
  return {hit=true,hitObject=hidden,hitPos=V.new(b.x,170,b.z)}
 end
 return {hit=false}
end
package.preload['openmw.nearby']=function()return nearby end
package.preload['openmw.self']=function()return self end
package.preload['openmw.types']=function()return {Actor={
 isSwimming=function()return mode=='swim'end,
 isDead=function()return mode=='corpse' or mode=='corpse_wall'end,
 getPathfindingAgentBounds=function()return {halfExtents=V.new(16,16,64)}end,
 objectIsInstance=function(o)return o.npc end}}end
package.preload['openmw.camera']=function()return {getYaw=function()return yaw end}end
package.preload['openmw.core']=function()return {getSimulationTime=function()return clock end}end
package.preload['openmw.util']=function()return {vector3=V.new}end
package.preload['openmw.vfs']=function()return {}end
package.preload['openmw.markup']=function()return {}end
local T=require('scripts.astrabridge.terrain');T.reset('test')
local r=T.observe();assert(r.supported and #r.rays==24 and #r.passages<=8)
assert(calls==192,'survey cost must be bounded')
local ref=r.passages[1].ref;assert(T.resolve(ref))
T.observe();assert(calls==192,'repeated paused observations use cache')
local mark=T.mark();self.position=V.new(40,0,0)
assert(not T.resolve(ref) and T.resolve(mark),'passages expire after movement, visited anchors remain')
self.cell={id='other_room'};assert(not T.resolve(mark),'markers never cross coordinate spaces')
self.cell={id='private_room'};self.position=V.new(0,0,0)
mode='stairs';r=T.observe(true);assert(r.rays[1].height_change_m<-.5)
mode='wall';r=T.observe(true);assert(r.rays[1].clear_m<1.5 and r.rays[1].status=='nav_boundary')
mode='actor';r=T.observe(true);assert(r.rays[1].status=='actor' and r.rays[1].clear_m<2.5)
local json=require('scripts.astrabridge.protocol').encode(r)
assert(not json:find('Unseen guard',1,true) and not json:find('private_',1,true) and not json:find('position',1,true))
mode='corpse';assert(not T.contact(V.new(0,0,0),V.new(0,100,0)),'lootable corpses are not standing actors')
mode='corpse_wall';assert(T.contact(V.new(0,0,0),V.new(0,100,0)).kind=='geometry','a corpse must not conceal the wall behind it')
mode='missing';r=T.observe(true);assert(#r.passages==0)
mode='swim';r=T.observe(true);assert(not r.supported and r.reason=='swimming_requires_manual_control')
T.reset('new');assert(not T.resolve(mark))
local restored=T.mark({2,-3,.5});local point=T.resolve(restored)
assert(point.x==140 and point.y==-210 and point.z==35,'restore only a relative recorded waypoint in the current space')
assert(not pcall(T.mark,{101,0,0}),'restored markers remain within the bounded local return distance')
local route=T.mark({0,2,0},{{0,0,0},{0,1,0},{0,2,0}})
assert(#T.route(route)==3 and T.route(route)[3].y==140)
assert(not pcall(T.mark,{0,2,0},{{2,0,0},{0,2,0}}),'a route must start at the current foot pose')
assert(not pcall(T.mark,{0,2,0},{{0,0,0},{0,1,0}}),'a route must end at the recorded marker')

-- Collision-only fallback must have continuous physical support. No gaps,
-- wrong-floor projections, or new obstacles can be crossed from memory.
local physical='floor'
nearby.castRay=function(a,b,opts)
    if a.x==b.x and a.y==b.y then
        if physical=='gap' and a.y>50 and a.y<90 then return {hit=false}end
        local z=physical=='stairs' and math.floor(a.y/30)*12 or physical=='wrong_floor' and 256 or 0
        if z>a.z or z<b.z then return {hit=false}end
        return {hit=true,hitPos=V.new(a.x,a.y,z),hitNormal=V.new(0,0,1)}
    end
    if physical=='closed_door' and a.y<60 and b.y>=60 then
        return {hit=true,hitPos=V.new(a.x,60,a.z)}
    end
    return {hit=false}
end
assert(T.walkLine(V.new(0,0,0),V.new(0,140,0)))
physical='stairs';assert(T.walkLine(V.new(0,0,0),V.new(0,120,48)))
for _,value in ipairs({'gap','wrong_floor','closed_door'}) do
    physical=value
    assert(not T.walkLine(V.new(0,0,0),V.new(0,140,0)),value..' must stop local path construction')
end
print('Bounded local survey: floors, walls, physical blocker, cache, stale refs, anchors and no hidden names passed')
