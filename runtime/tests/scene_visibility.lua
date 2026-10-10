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
local function object(name,y,npc)
    return {id='private_'..name,npc=npc,enabled=true,cell=room,isValid=function()return true end,
        type={record=function()return {name=name}end},getBoundingBox=function()
            local vertices={}
            for _,x in ipairs({-10,10})do for _,z in ipairs({-10,30})do vertices[#vertices+1]=V.new(x,y,z)end end
            return {center=V.new(0,y,10),halfSize=V.new(10,0,20),vertices=vertices}
        end}
end
local hidden=object('Hidden NPC',50,true)
local door=object('Visible door',100,false)
local wall={}
local blockDoor=false
package.preload['openmw.camera']=function()return {
    getPosition=function()return V.new(0,0,10)end,
    getYaw=function()return 0 end,getPitch=function()return 0 end,getFieldOfView=function()return 1 end,
    getViewDistance=function()return 7168 end,
    viewportToWorldVector=function()return V.new(0,1,0)end,
    worldToViewportVector=function(v)return V.new(640+v.x,360-v.z)end,
}end
package.preload['openmw.nearby']=function()return {
    actors={hidden},doors={door},containers={},items={},activators={},
    castRenderingRay=function(from,to)
        -- A zero-thickness door is hit only when the segment passes its plane.
        if to.y>100 and not blockDoor then return {hitObject=door,hitPos=V.new(0,100,10)} end
        return {hitObject=wall,hitPos=V.new(0,20,10)}
    end,
}end
package.preload['openmw.self']=function()return {cell=room,object={},position=V.new(0,0,0)}end
package.preload['openmw.types']=function()return {Actor={objectIsInstance=function(o)return o.npc end,
    activeEffects=function()return {getEffect=function()return nil end}end}}end
package.preload['openmw.util']=function()return {vector3=V.new,vector2=V.new}end
package.preload['openmw.core']=function()return {getSimulationTime=function()return 1 end,getGMST=function()return 192 end}end
package.preload['openmw.ui']=function()return {screenSize=function()return V.new(1280,720)end}end
package.preload['openmw.vfs']=function()return {}end
package.preload['openmw.markup']=function()return {}end
local scene=require('scripts.astrabridge.scene')
local result=scene.observe()
assert(#result.objects==1 and result.objects[1].name=='Visible door')
local json=require('scripts.astrabridge.protocol').encode(result)
assert(not json:find('Hidden NPC',1,true) and not json:find('private_',1,true))
blockDoor=true
assert(#scene.observe().objects==0,'extending a ray must never see through a wall')
assert(scene.resolve(result.objects[1].ref,true)==nil,'remembered targets still need clear line of sight')
print('Scene first-hit visibility, thin door, occluded NPC and no private identifiers passed')
