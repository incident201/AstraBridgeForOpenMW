package.path='mod/?.lua;'..package.path
math.atan2=math.atan2 or math.atan
local S=require('scripts.astrabridge.steering')
local Turning=require('scripts.astrabridge.turning')
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z or 0},V)end
function V.__add(a,b)return V.new(a.x+b.x,a.y+b.y,a.z+b.z)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
function V.__mul(a,b)return V.new(a.x*b,a.y*b,a.z*b)end
function V:length()return math.sqrt(self.x*self.x+self.y*self.y+self.z*self.z)end
local player={position=V.new(0,0,0),object={}}
local path={V.new(0,0),V.new(0,140),V.new(140,140),V.new(140,280)}
local obstacle=false
local function supported(p)
    if math.abs(p.z)>1 then return false end
    return math.abs(p.x)<=8 and p.y>=0 and p.y<=140
        or math.abs(p.y-140)<=8 and p.x>=0 and p.x<=140
        or math.abs(p.x-140)<=8 and p.y>=140 and p.y<=280
end
local function clear(a,b)
    if obstacle then return nil end
    local count=math.max(1,math.ceil((b-a):length()/2))
    for i=0,count do if not supported(a+(b-a)*(i/count)) then return nil end end
    return {a,b}
end
package.preload['openmw.self']=function()return player end
package.preload['openmw.util']=function()return {vector3=V.new}end
package.preload['openmw.core']=function()return {getRealTime=function()return 0 end}end
package.preload['openmw.types']=function()return {Actor={getRunSpeed=function()return 400 end,getWalkSpeed=function()return 200 end}}end
package.preload['openmw.nearby']=function()return {}end
package.preload['scripts.astrabridge.space']=function()return {}end
package.preload['scripts.astrabridge.mobility']=function()return {mode=function()return 'walk'end}end
package.preload['scripts.astrabridge.terrain']=function()return {
    walkLine=clear,contact=function()return obstacle and {kind='actor'} or nil end,
}end
local N=require('scripts.astrabridge.navigation')
for _,dt in ipairs({1/144,1/60,1/30,.1,.2}) do
    player.position=V.new(0,0)
    local n={goal=path[#path],path=path,index=1,status='planned',pathStatus='planned',sincePlan=0,inputDelayFrames=0}
    N.begin(n)
    local yaw=0;local reached=false
    for frame=1,math.ceil(20/dt) do
        if N.reached(n) then reached=true;break end
        local point=N.step(n,nil,dt)
        assert(point,'The supported corridor must remain traversable')
        local y,p,amount,forward,side=N.motion(n,point,dt,false,yaw)
        yaw=yaw+Turning.delta(yaw,y,dt)
        local displacement=V.new(math.sin(yaw)*forward+math.cos(yaw)*side,
            math.cos(yaw)*forward-math.sin(yaw)*side)*200*dt
        assert(clear(player.position,player.position+displacement),'Steering must not cut the unsupported inside of a corner')
        player.position=player.position+displacement
    end
    assert(reached,string.format('Reach the same goal: dt=%.5f position=%.3f,%.3f index=%d blocked=%s',dt,player.position.x,player.position.y,n.index,tostring(n.blockedBy)))
end
player.position=V.new(0,0)
local n={inputDelayFrames=0,path=path,index=2,goal=path[#path]};N.begin(n)
local _,_,amount=N.motion(n,V.new(0,100),.02,false,0)
assert(amount>0)
obstacle=true
local _,_,blocked,forward,side=N.motion(n,V.new(0,100),.02,false,0)
assert(blocked==0 and forward==0 and side==0 and n.driveAmount==0,'A new actor blocks immediately, bypassing smoothing')
assert(n.motor.stop_count==1)
obstacle=false
local f,s=S.controls(math.rad(45),0,1)
assert(f>0 and s>0 and math.abs(f*f+s*s-1)<1e-9,'Moderate turns use normal forward/sideways input without diagonal speed gain')
f,s=S.controls(math.rad(150),0,1)
assert(f==0 and s==0,'Large initial turns remain stationary')
f,s=S.controls(0,math.pi,1,0)
assert(f<0 and math.abs(s)<1e-9,'Movement follows the checked world direction even when view and actor headings differ')
local intermediate={inputDelayFrames=0,driveAmount=1}
local endpoint={inputDelayFrames=0,driveAmount=1}
assert(S.amount(intermediate,20,200,.02,false)==1 and S.amount(endpoint,20,200,.02,true)<1,
    'Dense intermediate samples do not cause endpoint braking')
print('Ground steering: supported narrow bends at 5–144 FPS, immediate obstruction stop, normalized controls and endpoint braking passed')
