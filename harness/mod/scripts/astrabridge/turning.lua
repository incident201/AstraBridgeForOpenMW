-- Shared finite angular speed for motor actions and paused camera previews.
local M={speed=math.rad(120)}
function M.angle(a)
    local value=(a+math.pi)%(2*math.pi)-math.pi
    if math.abs(value+math.pi)<1e-10 and a>0 then return math.pi end
    return value
end
function M.delta(current,target,dt)
    local limit=M.speed*math.min(math.max(dt,0),.25)
    return math.max(-limit,math.min(limit,M.angle(target-current)))
end
function M.advance(yaw,pitch,targetYaw,targetPitch,dt)
    local y=yaw+M.delta(yaw,targetYaw,dt)
    local p=pitch+M.delta(pitch,targetPitch,dt)
    return y,p,math.abs(M.angle(targetYaw-y))<.0001 and math.abs(targetPitch-p)<.0001
end
return M
