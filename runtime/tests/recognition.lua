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
local room={id='room'}
local distance,thirdPerson,limit,telekinesis=500,0,192,0
local blocked,focused,tooltipCalls=false,false,0
local obj={id='0x1000001',contentFile='morrowind.esm',recordId='secret_record',kind='Door',
    enabled=true,cell=room,isValid=function()return true end,
    type={record=function()return {name='Секретное имя'}end},getBoundingBox=function()
        return {center=V.new(0,distance,10),halfSize=V.new(10,0,20),
            vertices={V.new(-10,distance,-10),V.new(10,distance,30)}}
    end}
local function actor(o)return o.kind=='NPC' or o.kind=='Creature' end
local types={Actor={objectIsInstance=actor,isDead=function()return false end,
    activeEffects=function()return {getEffect=function(_,name)
        if name=='telekinesis' then return {magnitude=telekinesis} end
    end}end},Lockable={isLocked=function(o)return o.locked end,getTrapSpell=function(o)return o.trap end}}
for _,kind in ipairs({'NPC','Creature','Door','Container','Item','Activator'}) do
    types[kind]={objectIsInstance=function(o)return o.kind==kind end}
end
types.Door.isTeleport=function(o)return o.teleport end
local nearby={actors={},doors={obj},containers={},items={},activators={}}
nearby.castRenderingRay=function()
    return {hitObject=blocked and {id='wall',isValid=function()return false end} or obj,hitPos=V.new(0,distance,10)}
end
package.preload['openmw.camera']=function()return {
    getPosition=function()return V.new(0,0,10)end,getThirdPersonDistance=function()return thirdPerson end,
    getYaw=function()return 0 end,getPitch=function()return 0 end,getFieldOfView=function()return 1 end,
    getViewDistance=function()return 7168 end,
    viewportToWorldVector=function()return V.new(0,1,0)end,
    worldToViewportVector=function(v)return V.new(640+v.x,360-v.z)end,
}end
package.preload['openmw.nearby']=function()return nearby end
package.preload['openmw.self']=function()return {cell=room,object={},position=V.new(0,0,0)}end
package.preload['openmw.types']=function()return types end
package.preload['openmw.util']=function()return {vector3=V.new,vector2=V.new}end
package.preload['openmw.core']=function()return {getSimulationTime=function()return 1 end,getGMST=function()return limit end}end
package.preload['openmw.ui']=function()return {
    screenSize=function()return V.new(1280,720)end,
    _astraIsActivationTarget=function()return focused end,
    _astraDoorDescription=function()tooltipCalls=tooltipCalls+1;return 'Lock 50' end,
}end
package.preload['openmw.vfs']=function()return {}end
package.preload['openmw.markup']=function()return {}end
local scene=require('scripts.astrabridge.scene')
local recognition=require('scripts.astrabridge.recognition')
scene.reset('session_1')
local function row()return assert(scene.observe().objects[1])end
local far=row();local ref=far.ref
assert(not far.details_visible and not far.name and not far.description and tooltipCalls==0)
assert(not scene.interactionInfo(ref).name and not scene.identity(ref).name)
assert(not scene.pick(640,360,0).objects[1].name,'pick must not identify distant pixels')
distance=limit+.01
assert(not row().details_visible)
distance=limit
local close=row()
assert(close.ref==ref and close.name=='Секретное имя' and close.description=='Lock 50')
assert(close.details_visible and close.name_source=='observed' and not close.in_reach,
    'inspection uses the tooltip limit, not the motor reach safety margin')
assert(scene.interactionInfo(ref).name==close.name and scene.identity(ref).name==close.name)
assert(scene.pick(640,360,0).objects[1].name==close.name)
distance=limit+150;thirdPerson=150
assert(row().details_visible,'third-person camera offset must match engine focus distance')
thirdPerson=0
assert(not row().details_visible)
limit=400
assert(row().details_visible,'read the game limit instead of a fixed metre')
limit=192;distance=500;telekinesis=20
assert(row().details_visible,'non-actor telekinesis extends tooltip range')
obj.teleport=true;obj.locked=false
assert(not row().details_visible,'unlocked teleport doors do not allow telekinesis')
obj.locked=true
assert(row().details_visible)
obj.locked=false;obj.trap='trap'
assert(row().details_visible)
obj.kind='NPC';nearby.doors={};nearby.actors={obj}
assert(row().actor_kind=='npc' and not row().details_visible,'telekinesis cannot identify distant actors')
obj.kind='Creature'
assert(row().actor_kind=='creature')
focused=true
assert(row().details_visible,'real engine focus honours legal engine overrides')
focused=false;blocked=true;tooltipCalls=0
assert(#scene.observe().objects==0 and #scene.pick(640,360,0).objects==0)
assert(scene.interactionInfo(ref).reason=='target_not_visible' and not scene.identity(ref).name)
assert(tooltipCalls==0)
blocked=false;telekinesis=0
local key=row()._recognition_key
obj.id='0x2000001'
assert(row()._recognition_key==key,'content reordering must preserve instance identity')
obj.id='0x2000002'
assert(row()._recognition_key~=key,'another instance of the same record is unknown')
obj.contentFile=nil;obj.id='@0x1234'
local dynamicKey=row()._recognition_key
local saved=scene.saveRecognition()
scene.loadRecognition(nil);scene.reset('session_2')
assert(row()._recognition_key~=dynamicKey,'a recycled dynamic FormId must not inherit a name')
scene.loadRecognition(saved);scene.reset('session_3')
assert(row()._recognition_key==dynamicKey,'saved instance tokens survive load/restart')
assert(not require('scripts.astrabridge.protocol').encode({token=saved[1].token}):find('Секретное имя',1,true))
print('Scene inspection range, all entry points, actor kinds, occlusion and instance identity passed')
