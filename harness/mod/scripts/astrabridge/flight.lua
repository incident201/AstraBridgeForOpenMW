-- Bounded local flight using ordinary forward input and finite player turns.
-- Destination coordinates stay private to the motor.
local M={}
function M.new(seconds,verticalOnly) return {elapsed=0,limit=seconds,stalled=0,verticalOnly=verticalOnly} end
function M.step(s,c,dt)
    s.elapsed=s.elapsed+dt
    if not c.levitation then return {reason='levitation_ended'} end
    local horizontal=s.verticalOnly and 0 or math.sqrt(c.x*c.x+c.y*c.y)
    local remaining=math.sqrt(horizontal*horizontal+c.z*c.z)
    if remaining<=14 then return {reason='arrived'} end
    if s.elapsed>=s.limit then return {reason='step_limit'} end
    -- Inside the arrival tolerance, tiny sideways drift must not turn a
    -- vertical ascent into a 180-degree camera correction.
    local yaw=horizontal>14 and math.atan2(c.x,c.y) or c.yaw
    local pitch=math.max(-math.rad(89.5),math.min(math.rad(89.5),-math.atan2(c.z,horizontal<=14 and 0 or horizontal)))
    local angle=(yaw-c.yaw+math.pi)%(2*math.pi)-math.pi
    local pitchTolerance=horizontal<=14 and math.rad(1) or math.rad(8)
    local aligned=math.abs(angle)<math.rad(8) and math.abs(pitch-c.pitch)<pitchTolerance
    -- Contact jitter is movement, but not progress toward the requested point.
    if not aligned or not s.bestDistance or remaining<s.bestDistance-3 then
        s.bestDistance=remaining;s.stalled=0
    else s.stalled=s.stalled+dt end
    if s.stalled>1.5 then return {reason='blocked'} end
    return {yaw=yaw,pitch=pitch,move=aligned and math.min(1,remaining/math.max(40,c.speed*math.max(dt,.2))) or 0}
end
return M
