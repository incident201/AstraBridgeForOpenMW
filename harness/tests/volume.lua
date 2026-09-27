package.path='mod/?.lua;'..package.path
math.atan2=math.atan2 or math.atan
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z},V)end
function V.__add(a,b)return V.new(a.x+b.x,a.y+b.y,a.z+b.z)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
function V.__mul(a,b)return V.new(a.x*b,a.y*b,a.z*b)end
function V.__div(a,b)return a*(1/b)end
function V:length()return math.sqrt(self.x^2+self.y^2+self.z^2)end
function V:normalize()return self/self:length()end
local self={position=V.new(0,0,0),object={},cell={id='fixture',waterLevel=0}}
local mode='air';local obstacle
local nearby={NAVIGATOR_FLAGS={Walk=1,Swim=2,UsePathgrid=8},FIND_PATH_STATUS={Success=1,PartialPath=2}}
-- Real segment/AABB intersection; all seven body rays use the same geometry.
function nearby.castRay(a,b,options)
 assert(options.ignore==self.object)
 if not obstacle then return {hit=false} end
 local low,high=0,1
 for _,axis in ipairs({'x','y','z'}) do
  local delta=b[axis]-a[axis];local min,max=obstacle[axis][1],obstacle[axis][2]
  if math.abs(delta)<1e-9 then if a[axis]<min or a[axis]>max then return {hit=false} end
  else
   local p,q=(min-a[axis])/delta,(max-a[axis])/delta
   low=math.max(low,math.min(p,q));high=math.min(high,math.max(p,q))
   if low>high then return {hit=false} end
  end
 end
 return {hit=true,hitObject=obstacle.actor and {} or nil}
end
local nativeCalls=0
function nearby.findPath(a,b,args)
 nativeCalls=nativeCalls+1;assert(args.includeFlags==11);return 1,{b}
end
package.preload['openmw.util']=function()return {vector3=V.new}end
package.preload['openmw.self']=function()return self end
package.preload['openmw.nearby']=function()return nearby end
package.preload['openmw.types']=function()return {Actor={getPathfindingAgentBounds=function()return {halfExtents=V.new(20,20,45)}end,
 objectIsInstance=function()return true end,getWalkSpeed=function()return 200 end}}end
package.preload['scripts.astrabridge.mobility']=function()return {mode=function()return mode end,has=function()return false end,
 surface=function(p)return p end,flags=function()return 3 end}end
local volume=require('scripts.astrabridge.volume')
local goal=V.new(0,300,0)
assert(#volume.plan(self.position,goal)==1)
obstacle={x={-45,45},y={100,180},z={-1000,1000},actor=true}
assert(volume.contact(self.position,goal).kind=='actor')
local path=assert(volume.plan(self.position,goal));assert(#path==2)
assert(not volume.contact(self.position,path[1]) and not volume.contact(path[1],path[2]),'both detour legs clear the whole body')
obstacle={x={-10000,10000},y={100,180},z={-10000,10000}}
assert(not volume.plan(self.position,goal),'sealed wall must not become a successful plan')
obstacle=nil
local N=require('scripts.astrabridge.navigation')
local n=N.new({groundPoint=V.new(0,0,280),freeDestination=true});N.begin(n)
local waypoint=N.step(n,nil,.2)
local yaw,pitch,fraction=N.motion(n,waypoint,.2,false,.75)
assert(yaw==.75 and pitch< -1.5 and fraction>0,'vertical ascent keeps heading and pitches up')
assert(N.report(n).movement_mode=='air' and nativeCalls==0)
self.position=V.new(0,0,270);local _,_,brake=N.motion(n,V.new(0,0,280),.2,false,.75)
assert(brake<1,'vertical low-FPS arrival brakes using 3D distance')
mode='walk';self.position=V.new(0,0,140);N.step(n,nil,.1)
assert(n.mode=='walk' and nativeCalls==1,'landing/effect transition replans using native pathfinding')
mode='swim';self.position=V.new(0,0,-220)
n=N.new({groundPoint=V.new(0,100,-220),freeDestination=true})
assert(n.volume and N.report(n).movement_mode=='swim')
print('3D body collision, actor detour, sealed wall, vertical motion/braking and movement transitions passed')
