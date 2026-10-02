-- Player-observable motion only. No terrain queries or predicted landing point.
local M={}
local previous,velocity
local function round(v) return math.floor(v*100+.5)/100 end
function M.reset() previous=nil;velocity=nil end
function M.sample(time,position,cell,units)
    if previous then
        local dt=time-previous.time
        local distance=(position-previous.position):length()/units
        if cell~=previous.cell or dt<0 or dt>1 or (dt==0 and distance>.001) then
            velocity=nil
        elseif dt>0 then
            -- Reject discontinuities such as console teleport/load in development.
            velocity=distance/dt<200 and (position.z-previous.position.z)/units/dt or nil
        end
    end
    previous={time=time,position=position,cell=cell}
end
function M.state(ground,water,levitation)
    local speed=ground and 0 or velocity
    local phase=water and 'swimming' or levitation and 'levitating' or ground and 'grounded'
        or speed and speed>.1 and 'ascending' or speed and speed<-.1 and 'descending' or 'airborne'
    return {air_state=phase,vertical_speed_mps=speed and round(speed)}
end

M.directions={none={0,0},forward={1,0},back={-1,0},left={0,-1},right={0,1},
    ['forward-left']={1,-1},['forward-right']={1,1},['back-left']={-1,-1},['back-right']={-1,1}}
function M.begin(kind,ground,z,health)
    return {kind=kind,started_airborne=not ground,took_off=false,airborne_observed=not ground,
        startZ=z,peakZ=z,health=health,damage=0}
end
function M.update(a,ground,water,z,health)
    if not ground and not water then
        a.airborne_observed=true
        if not a.started_airborne then a.took_off=true end
    end
    a.landed=a.airborne_observed and ground and not water
    a.peakZ=math.max(a.peakZ,z)
    if a.health and health then a.damage=a.damage+math.max(0,a.health-health) end
    a.health=health
end
function M.report(a,units)
    return {started_airborne=a.started_airborne,took_off=a.took_off,landed=a.landed or false,
        peak_rise_m=round((a.peakZ-a.startZ)/units),damage_taken=round(a.damage)}
end
function M.reason(a,ground,water,levitation,elapsed,limit)
    if water then return 'entered_water' end
    if levitation then return 'levitation_active' end
    if a.landed then return a.kind=='landed' and 'condition_met' or 'landed' end
    if a.kind=='landed' and ground then return 'condition_met' end
    if a.kind=='jump' and not a.took_off and elapsed>=math.min(.5,limit) then return 'jump_not_started' end
    if elapsed>=limit then
        return a.kind=='jump' and 'airborne' or a.kind=='landed' and 'condition_timeout' or 'duration'
    end
end
return M
