-- Local body-envelope sensing for flight/swimming. Never enumerates hidden
-- objects or reads map geometry; every leg is checked against current physics.
local nearby=require('openmw.nearby')
local types=require('openmw.types')
local self=require('openmw.self')
local util=require('openmw.util')
local M={}
function M.contact(from,to)
    local b=types.Actor.getPathfindingAgentBounds(self).halfExtents
    local radius=math.max(b.x,b.y)*.85
    local shifts={util.vector3(0,0,b.z),util.vector3(radius,0,b.z),util.vector3(-radius,0,b.z),
        util.vector3(0,radius,b.z),util.vector3(0,-radius,b.z),util.vector3(0,0,4),util.vector3(0,0,b.z*1.9)}
    for _,shift in ipairs(shifts) do
        local hit=nearby.castRay(from+shift,to+shift,{ignore=self.object})
        if hit.hit then
            return {kind=hit.hitObject and types.Actor.objectIsInstance(hit.hitObject) and 'actor' or 'geometry'}
        end
    end
end
function M.plan(from,goal,swimming,water)
    local d=goal-from
    local length=d:length()
    if length<1 then return {goal} end
    local join=from+d*math.min(1,420/length)
    if not M.contact(from,join) then return {join} end
    local horizontal=math.sqrt(d.x*d.x+d.y*d.y)
    local side=horizontal>1 and util.vector3(d.y/horizontal,-d.x/horizontal,0) or util.vector3(1,0,0)
    local forward=d/length
    local best,cost
    for _,radius in ipairs({85,150,230}) do
        for _,offset in ipairs({side*radius,side*-radius,util.vector3(0,0,radius),util.vector3(0,0,-radius),
            side*radius+util.vector3(0,0,radius),side*-radius+util.vector3(0,0,radius)}) do
            local mid=from+forward*math.min(70,length*.2)+offset
            -- Water routing must not propose flying over a bank. Native Walk|Swim
            -- paths handle leaving the water; this detour stays in the volume.
            if (not swimming or not water or mid.z<water-20)
                and not M.contact(from,mid) and not M.contact(mid,join) then
                local score=(mid-from):length()+(join-mid):length()
                if not cost or score<cost then best={mid,join};cost=score end
            end
        end
        if best then break end
    end
    return best
end
return M
