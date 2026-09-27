package.path='mod/?.lua;'..package.path
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z or 0},V)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
local yaw=math.pi/2
local self={position=V.new(987654,456789,200),cell={id='SECRET_WORLD_CELL',isExterior=true}}
package.preload['openmw.self']=function()return self end
package.preload['openmw.camera']=function()return {getYaw=function()return yaw end}end
package.preload['openmw.vfs']=function()return {}end
package.preload['openmw.markup']=function()return {}end
local T=require('scripts.astrabridge.trajectory')
local P=require('scripts.astrabridge.protocol')
-- Engine storage drops Lua metatables; empty lists must still serialize as lists.
local empty=P.encode({trajectory={samples={}},terrain={rays={},passages={}},effects={},steps={}})
for _,field in ipairs({'samples','rays','passages','effects','steps'}) do assert(empty:find('"'..field..'":[]',1,true))end
T.reset('public_session');local r=T.report()
assert(#r.samples==1 and r.samples[1].forward_m==0 and r.start_heading_deg==90)
local segment=r.ref
assert(#T.report(r.sequence,segment).samples==0,'paused observations must not duplicate the path')
self.position=V.new(987724,456789,200);T.sample(false)
r=T.report(1,segment);assert(#r.samples==1 and r.samples[1].forward_m==1 and r.samples[1].sideways_m==0)
self.cell={id='OTHER_GRID_CELL',isExterior=true}
assert(T.report(2,segment).ref==segment,'an exterior grid boundary is not a teleport')
self.cell={id='SECRET_INTERIOR'};r=T.report(2,segment)
assert(r.ref~=segment and r.sequence==1 and r.samples[1].forward_m==0,'never draw a line through a teleport')
segment=r.ref
for i=1,600 do self.position=V.new(987724+i*70,456789,200);T.sample(false)end
r=T.report(1,segment);assert(#r.samples==512 and r.sparse,'bounded backlog must declare its missing samples')
local encoded=P.encode(r)
assert(not encoded:find('987724') and not encoded:find('SECRET') and not encoded:find('position'))
local old=r.ref
self.position=V.new(900000,400000,200);r=T.report(r.sequence,old)
assert(r.ref~=old and r.samples[1].forward_m==0,'same-space travel must never draw a path across unseen territory')
print('Own-motion trajectory: relative origin, cursor, pauses, exterior continuity, teleports and bounded gaps passed')

T.reset('stream');self.cell={id='first'};self.position=V.new(0,0,0)
T.sample(true);T.flush()
self.position=V.new(70,0,0);T.sample(true)
self.cell={id='second'};self.position=V.new(300,0,0);T.sample(true)
local chunks=T.flush()
assert(#chunks==2 and chunks[1].frame.space=='first' and chunks[2].frame.space=='second')
assert(chunks[1].trajectory.samples[1].forward_m==1,'preserve the last old-cell points')
assert(#T.flush()==0,'do not replay acknowledged samples')
local count=0
for i=1,1000 do
    self.position=V.new(300+i*70,0,0);T.sample(true)
    if i%5==0 then for _,chunk in ipairs(T.flush()) do count=count+#chunk.trajectory.samples end end
end
assert(count==1000,'streaming must preserve a path longer than the bounded Lua ring')
