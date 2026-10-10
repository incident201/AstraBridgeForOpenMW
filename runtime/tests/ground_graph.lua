-- Physics-backed route planning on a narrow curved deck. Floor support is
-- represented by checked strips, independent of the search implementation.
local mod=arg[1] or 'mod'
math.atan2=math.atan2 or math.atan
local V={};V.__index=V
function V.new(x,y,z)return setmetatable({x=x,y=y,z=z or 0},V)end
function V.__add(a,b)return V.new(a.x+b.x,a.y+b.y,a.z+b.z)end
function V.__sub(a,b)return V.new(a.x-b.x,a.y-b.y,a.z-b.z)end
function V.__mul(a,b)return V.new(a.x*b,a.y*b,a.z*b)end
function V:length()return math.sqrt(self.x*self.x+self.y*self.y+self.z*self.z)end
local function horizontal(v)return math.sqrt(v.x*v.x+v.y*v.y)end
local player={position=V.new(0,0,0),object={},cell={}}
local deck,forcedCap,budget,queries
local function supported(p)
    for i=1,#deck-1 do
        local a,b=deck[i],deck[i+1]
        local d=b-a
        local t=math.max(0,math.min(1,((p-a).x*d.x+(p-a).y*d.y)/(d.x*d.x+d.y*d.y)))
        if horizontal(p-(a+d*t))<=8 then return true end
    end
    return false
end
local function safe(a,b)
    if horizontal(b-a)>420 or math.abs(a.z)>0.01 or math.abs(b.z)>0.01 then return nil end
    for i=0,math.max(1,math.ceil(horizontal(b-a)/2)) do
        local p=a+(b-a)*(i/math.max(1,math.ceil(horizontal(b-a)/2)))
        if not supported(p) then return nil end
    end
    return {a,b}
end
local terrain={}
terrain.walkLine=function(a,b,opts)
    if budget then
        if queries>=budget then error('review_query_cutoff')end
        queries=queries+1
    end
    return safe(a,b)
end
terrain.contact=function()return nil end
terrain.withQueryBudget=function(limit,fn)
    budget=forcedCap or limit;queries=0
    local ok,result=pcall(fn)
    budget=nil;terrain.lastQueryCount=queries
    if not ok and not tostring(result):find('review_query_cutoff',1,true)then error(result)end
    return ok and result or nil
end
local nearby={NAVIGATOR_FLAGS={Walk=1,Swim=2,UsePathgrid=8},FIND_PATH_STATUS={Success=1,PartialPath=2}}
nearby._astraActorSweep=function()return {hit=false},1 end
nearby.findPath=function(a,b)return 2,{a,V.new(b.x,b.y,-100)}end
package.preload['openmw.nearby']=function()return nearby end
package.preload['openmw.self']=function()return player end
package.preload['openmw.util']=function()return {vector3=V.new}end
package.preload['openmw.types']=function()return {Actor={
    getPathfindingAgentBounds=function()return {halfExtents=V.new(29.28,28.48,66.5)}end,
    objectIsInstance=function()return false end,
}}end
package.preload['scripts.astrabridge.space']=function()return {key=function()return 'review'end}end
package.preload['scripts.astrabridge.mobility']=function()return {
    surface=function(p)return p end,flags=function(f)return f.Walk+f.Swim end,
    has=function()return false end,mode=function()return 'walk'end,
}end
package.preload['scripts.astrabridge.terrain']=function()return terrain end
local N=assert(loadfile(mod..'/scripts/astrabridge/navigation.lua'))()
local function reset(points,cap)
    player.position=V.new(0,0,0);deck=points;forcedCap=cap
end
local function validate(n)
    assert(n.localPath and n.path and not n.endpointMismatch,'a checked local route must replace wrong-floor navigation')
    local previous=player.position
    for _,point in ipairs(n.path)do assert(safe(previous,point),'every installed edge stays on the curved deck');previous=point end
end
local function finish(n)
    for i=1,100 do
        local point=N.step(n,nil,.1)
        if not point then assert(N.reached(n),'path end must reach the original goal');return end
        player.position=point
    end
    error('prefix/step recursion or route failed to finish within 100 exact waypoint visits')
end
reset({V.new(0,0),V.new(0,280),V.new(280,280)})
local shortGoal=V.new(280,280)
local short=N.new({groundPoint=shortGoal})
validate(short)
assert(short.goal==shortGoal and not short.localPrefix,'short curving route must reach the unchanged exact goal')
finish(short)
reset({V.new(0,0),V.new(0,112),V.new(448,112),V.new(448,0),V.new(576,0)})
local longGoal=V.new(576,0)
local long=N.new({groundPoint=longGoal})
validate(long)
assert(long.localPrefix and horizontal(long.path[#long.path]-longGoal)<486,'long curve must preserve >90-unit checked prefix progress')
finish(long)
assert(long.goal==longGoal,'prefix replanning must preserve the original goal identity')
reset({V.new(0,0),V.new(0,112),V.new(448,112),V.new(448,0),V.new(576,0)},110)
local limited=N.new({groundPoint=longGoal})
validate(limited)
assert(limited.localPrefix and terrain.lastQueryCount==110,'query cutoff must retain an already checked useful prefix')
reset({V.new(0,0),V.new(0,280),V.new(280,280)})
local wrongHeight=N.new({groundPoint=V.new(280,280,100)})
assert(not wrongHeight.localPath and wrongHeight.endpointMismatch,'curved graph cannot retarget an unreachable goal height')
reset({V.new(0,0),V.new(0,84),V.new(84,84)})
local void=N.new({groundPoint=V.new(280,280)})
assert(not void.localPath and void.endpointMismatch,'short graph must not substitute a nearer point for its exact unsupported goal')
print('Curved short route, long checked prefix and unchanged-goal completion passed.')
print('Checked prefix survives 110-query cutoff; wrong goal height and unsupported exact goal rejected.')
