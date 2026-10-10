package.path='mod/?.lua;'..package.path
math.atan2=math.atan2 or math.atan
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z or 0},V)end
function V.__add(a,b)return V.new(a.x+b.x,a.y+b.y,a.z+b.z)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
function V.__mul(a,b)return V.new(a.x*b,a.y*b,a.z*b)end
function V:length()return math.sqrt(self.x^2+self.y^2+self.z^2)end
function V:normalize()return self*(1/self:length())end
function V:dot(b)return self.x*b.x+self.y*b.y+self.z*b.z end
local room={id='private_room'}
local player={position=V.new(0,0,0),cell=room,object={}}
local origin,far,yaw,scale,clock=V.new(0,0,100),5000,0,3,0
local function forward()return V.new(math.sin(yaw),math.cos(yaw),0)end
local function right()return V.new(math.cos(yaw),-math.sin(yaw),0)end
local camera={getPosition=function()return origin end,getViewDistance=function()return far end,
    getYaw=function()return yaw end,getPitch=function()return 0 end,getFieldOfView=function()return 1 end,
    viewportToWorldVector=function(p)return (forward()+right()*((p.x*2-1)*1.2)+V.new(0,0,(1-p.y*2)*.4))*scale end,
    worldToViewportVector=function(p)
        local d=p-origin;local depth=d:dot(forward())
        return V.new(500+d:dot(right())/depth*500/1.2,500-d.z/depth*500/.4)
    end}
local function object(id,center,half,kind)
    local o={id=id,center=center,half=half,kind=kind or 'door',enabled=true,cell=room,
        isValid=function()return true end,type={record=function()return {name='Uninspected object'}end}}
    function o:getBoundingBox()
        local vertices={}
        for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
            vertices[#vertices+1]=self.center+V.new(self.half.x*x,self.half.y*y,self.half.z*z)
        end end end
        return {center=self.center,halfSize=self.half,vertices=vertices}
    end
    return o
end
local objects,wall,mode={},nil,'objects'
local waterLevel,hitDepth=nil,4500
local endpoints={}
local function intersection(a,b,o)
    local d=b-a;local lo,hi=0,1
    for _,axis in ipairs({'x','y','z'})do
        local lower,upper=o.center[axis]-o.half[axis],o.center[axis]+o.half[axis]
        if math.abs(d[axis])<1e-9 then
            if a[axis]<lower or a[axis]>upper then return nil end
        else
            local x,y=(lower-a[axis])/d[axis],(upper-a[axis])/d[axis]
            if x>y then x,y=y,x end
            lo,hi=math.max(lo,x),math.min(hi,y)
            if lo>hi then return nil end
        end
    end
    return a+d*lo,lo
end
local nearby={actors={},doors={},containers={},items={},activators={},findPath=function()end}
nearby.castRenderingRay=function(a,b,options)
    assert(options.ignore==player.object);endpoints[#endpoints+1]=b
    if mode=='miss' then return {hit=false}end
    if mode=='outside' then return {hit=true,hitObject=objects[1],hitPos=a+forward()*(far+1)}end
    if mode=='floor' or mode=='water_wall' or mode=='bridge' then
        local point=a+(b-a)*(hitDepth/far)
        return {hit=true,hitPos=point,hitNormal=mode=='water_wall' and V.new(1,0,0) or V.new(0,0,1)}
    end
    local best,t
    local candidates={};for _,o in ipairs(objects)do candidates[#candidates+1]=o end
    if wall then candidates[#candidates+1]=wall end
    for _,o in ipairs(candidates)do
        local point,value=intersection(a,b,o)
        if value and (not t or value<t)then best={hit=true,hitObject=o,hitPos=point};t=value end
    end
    return best or {hit=false}
end
package.preload['openmw.camera']=function()return camera end
package.preload['openmw.nearby']=function()return nearby end
package.preload['openmw.self']=function()return player end
package.preload['openmw.util']=function()return {vector3=V.new,vector2=V.new}end
package.preload['openmw.ui']=function()return {screenSize=function()return V.new(1000,1000)end}end
package.preload['openmw.core']=function()return {getSimulationTime=function()return clock end,getGMST=function()return 192 end}end
package.preload['openmw.types']=function()return {
    Actor={objectIsInstance=function(o)return o.kind=='actor'end,getPathfindingAgentBounds=function()return {}end,
        activeEffects=function()return {getEffect=function()return nil end}end},
    Door={objectIsInstance=function(o)return o.kind=='door'end,isTeleport=function()return false end},
    Item={objectIsInstance=function(o)return o.kind=='item'end}}
end
package.preload['openmw.vfs']=function()return {}end
package.preload['openmw.markup']=function()return {}end
package.preload['scripts.astrabridge.mobility']=function()return {waterLevel=function()return waterLevel end}end
package.preload['scripts.astrabridge.navigation']=function()return {
    new=function(g)return {goal=g.groundPoint,status='planned'}end,report=function(n)return {status=n.status}end}
end
local S=require('scripts.astrabridge.scene');S.reset('range')
local function only(o)
    objects={o};nearby.doors={o};wall=nil;mode='objects';endpoints={}
end

-- Screen edges belong to a depth plane, not a radius around the camera.
local edge=object('edge',V.new(3400,4000,100),V.new(10,10,20));only(edge)
assert((edge.center-origin):length()>far)
local screen=camera.worldToViewportVector(edge.center)
local picked=S.pick(screen.x,screen.y,0)
assert(#picked.objects==1 and not picked.objects[1].name and not picked.objects[1].details_visible)
assert(math.abs((endpoints[1]-origin):dot(forward())-far)<1e-6)
assert((endpoints[1]-origin):length()>far)
assert(#S.observe().objects==1)
far=3000
assert(#S.pick(screen.x,screen.y,0).objects==0 and #S.observe().objects==0,'current camera settings take effect immediately')
far=5000
assert(S.orientation().view_distance_m==71.43)
only(object('beyond',V.new(0,5100,100),V.new(10,10,20)))
assert(#S.pick(500,500,0).objects==0 and #S.observe().objects==0)

-- Bounds centres and sample targets can be clipped while their front surface is visible.
local crossing=object('crossing',V.new(0,5200,100),V.new(20,400,20));only(crossing)
assert(#S.observe().objects==1 and #S.pick(500,500,0).objects==1)
far=4800;assert(#S.observe().objects==1,'the far plane itself is inclusive')
far=4799;assert(#S.observe().objects==0)
far=5000;mode='outside'
assert(#S.observe().objects==0 and #S.pick(500,500,0).objects==0,'actual hits beyond the plane are rejected')
mode='objects';wall=object('wall',V.new(0,2000,100),V.new(50,50,50),'geometry')
assert(#S.observe().objects==0 and #S.pick(500,500,0).objects==0,'first-hit geometry still occludes a selected object')

-- Turning away must preserve the existing finite motor grace, including at the view edge.
only(edge);local row=S.observe().objects[1];assert(row)
yaw=math.pi
assert(S.resolve(row.ref)==nil and S.resolve(row.ref,true),'a remembered ref can remain reachable behind the camera')
wall=object('behind_wall',V.new(1700,2000,100),V.new(100,100,100),'geometry')
assert(not S.resolve(row.ref,true),'motor grace never bypasses a physical occluder')
wall=nil;clock=61;assert(not S.resolve(row.ref,true),'motor grace remains finite')
clock=0;yaw=0

-- Visible floor acquisition and suggestions have the same camera boundary.
nearby.doors={};objects={};mode='floor';hitDepth=4500
local floor=S.groundPoint(900,750)
assert(floor and (floor-origin):length()>far and floor.y==4500)
local targets=S.groundTargets();assert(#targets>0)
for _,point in ipairs(targets)do assert(point.distance_m>30)end
far=4000
assert(not S.groundPoint(900,750) and #S.groundTargets()==0)
far=5000

-- Water uses consistent distances on oblique rays, including nearby occluders.
waterLevel=0;far=1000
mode='water_wall';hitDepth=450
assert(not S.groundPoint(900,750),'a wall before the water must not reveal a water target behind it')
mode='floor';hitDepth=800
assert(S.groundPoint(900,750).z==0,'a bottom beyond the water permits the visible water surface')
mode='bridge';hitDepth=400
assert(S.groundPoint(900,750).z>0,'a bridge before the water keeps its actual visible surface')
mode='miss';far=400
assert(not S.groundPoint(900,750),'water outside the current view distance is not selected')
far=1000;assert(S.groundPoint(900,750).z==0)
print('Current camera range: depth edges, settings, partial bounds, first hits, motor grace, floor and water passed')
