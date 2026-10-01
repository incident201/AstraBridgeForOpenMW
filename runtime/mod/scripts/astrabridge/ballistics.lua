-- Private motor math; no game objects, world coordinates or target stats escape.
local M={}
local function norm(v)return math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)end
function M.solve(r,v,speed,gravity,frame)
    if speed<=0 or gravity<0 then return nil end
    local function velocity(t)
        return {x=r.x/t+v.x,y=r.y/t+v.y,
            z=r.z/t+v.z+gravity*(t+math.max(0,frame or 0))*.5}
    end
    -- The engine applies gravity before moving the projectile each frame.
    -- The frame term accounts for that extra half-step at a low render FPS.
    local maximum=math.min(8,math.max(1,norm(r)/speed*4))
    local low,high=.0001,nil
    for i=1,64 do
        local t=maximum*i/64
        if norm(velocity(t))<=speed then high=t;break end
        low=t
    end
    if not high then return nil end
    for _=1,24 do
        local t=(low+high)*.5
        if norm(velocity(t))>speed then low=t else high=t end
    end
    return velocity(high),high
end
function M.sample(state,point,dt)
    local velocity={x=0,y=0,z=0}
    if state.previous and dt>0 and dt<.5 then
        local raw={x=(point.x-state.previous.x)/dt,y=(point.y-state.previous.y)/dt,z=(point.z-state.previous.z)/dt}
        if norm(raw)<840 then
            local alpha=1-math.exp(-dt/.3)
            local old=state.velocity or velocity
            velocity={x=old.x+(raw.x-old.x)*alpha,y=old.y+(raw.y-old.y)*alpha,z=old.z+(raw.z-old.z)*alpha}
        end
    end
    state.previous={x=point.x,y=point.y,z=point.z};state.velocity=velocity
    return velocity
end
return M
