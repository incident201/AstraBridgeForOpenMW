-- Ground-route steering. Targets are selected by navigation and every proposed
-- movement corridor is checked against the physical body and actual support.
local M={}
local function angle(v)
    return (v+math.pi)%(2*math.pi)-math.pi
end
local function counters()
    return {
        moving_seconds=0, turning_seconds=0, blocked_seconds=0,
        planning_seconds=0, stop_count=0, target_changes=0,
        planner_queries=0, planner_slices=0, max_update_seconds=0,
    }
end
function M.begin(state)
    state.driveAmount=0
    state.wasDriving=false
    state.motorTarget=nil
    state.motor=counters()
end

function M.amount(state,distance,speed,dt,final,turn)
    local delay=state.inputDelayFrames or 2
    local queued=(state.lastMovement or 0)*delay
    -- Brake for the distance we can actually traverse before new input takes
    -- effect. Only the final destination needs the longer settling horizon.
    local horizon=math.max(dt,final and .2 or .06)*math.max(1,delay)
    local safe=math.min(1,math.max(0,distance-queued)/math.max(1,speed*horizon))
    local desired=safe
    if turn then desired=desired*(1-.55*math.min(1,math.abs(turn)/math.pi)) end
    -- Smooth recovery/acceleration, but never retain speed above the current
    -- checked distance cap. A newly blocked corridor bypasses this completely.
    local previous=state.driveAmount or 0
    local change=(desired>previous and 4 or 6)*dt
    local smoothed=math.max(previous-change,math.min(previous+change,desired))
    state.driveAmount=math.min(safe,smoothed)
    return state.driveAmount
end

function M.controls(yaw,facing,amount,viewError)
    local error=angle(yaw-facing)
    -- Keep very large initial turns stationary; moderate turns can use normal
    -- forward/sideways controls without waiting for camera alignment.
    if math.abs(viewError or error)>math.rad(100) then return 0,0 end
    return math.cos(error)*amount,math.sin(error)*amount
end

function M.sample(state,dt,amount,reason,point)
    local stats=state.motor or counters()
    state.motor=stats
    if point and point~=state.motorTarget then
        stats.target_changes=stats.target_changes+1
        state.motorTarget=point
    end
    local moving=amount>.01
    if moving then stats.moving_seconds=stats.moving_seconds+dt
    elseif reason=='turn' then stats.turning_seconds=stats.turning_seconds+dt
    elseif reason=='planning' then stats.planning_seconds=stats.planning_seconds+dt
    else stats.blocked_seconds=stats.blocked_seconds+dt end
    if state.wasDriving and not moving then stats.stop_count=stats.stop_count+1 end
    state.wasDriving=moving
end

function M.report(state)
    local result={}
    for k,v in pairs(state.motor or {}) do result[k]=math.floor(v*1000+.5)/1000 end
    return result
end
return M
