-- Memory of the player's own travelled path, in metres relative to this visit's
-- origin. No world-space coordinates or other objects enter the public record.
local self=require('openmw.self')
local camera=require('openmw.camera')
local Space=require('scripts.astrabridge.space')
local P=require('scripts.astrabridge.protocol')
local M={}
local namespace,serial,space,origin,heading,rows,sequence='boot',0,nil,nil,0,{},0
local function round(x)return math.floor(x*100+.5)/100 end
function M.reset(value)
    namespace,serial,space,origin,rows,sequence=value,0,nil,nil,{},0
end
function M.sample(force)
    if not self.cell or not self.position then return end
    local key=Space.key(self.cell)
    if space~=key then
        space,origin,heading,rows,sequence=key,self.position,camera.getYaw(),{},0
        serial=serial+1
    end
    local d=self.position-origin
    local f=(d.x*math.sin(heading)+d.y*math.cos(heading))/70
    local s=(d.x*math.cos(heading)-d.y*math.sin(heading))/70
    local z=d.z/70
    local yaw=math.deg(camera.getYaw())%360
    local last=rows[#rows]
    if last and (f-last.forward_m)^2+(s-last.sideways_m)^2+(z-last.vertical_m)^2>12^2 then
        -- Travel services/scripts can teleport inside the same exterior world.
        -- A discontinuity is a new visit, never a path through unseen territory.
        origin,heading,rows,sequence=self.position,camera.getYaw(),{},0
        serial=serial+1;f,s,z=0,0,0;last=nil
    end
    if last then
        local distance=(f-last.forward_m)^2+(s-last.sideways_m)^2+(z-last.vertical_m)^2
        local turn=math.abs((yaw-last.heading_deg+180)%360-180)
        if distance<(force and .025^2 or .35^2) and turn<(force and .5 or 20) then return end
    end
    sequence=sequence+1
    rows[#rows+1]={sequence=sequence,forward_m=round(f),sideways_m=round(s),vertical_m=round(z),heading_deg=round(yaw)}
    if #rows>512 then table.remove(rows,1) end
end
-- Controller-only coordinate-frame metadata, removed before public validation.
-- Contains this player's origin, not any level geometry or object coordinates.
function M.frame()
    if not origin then return nil end
    return {space=space,origin={origin.x/70,origin.y/70,origin.z/70}}
end
function M.report(after,segment)
    M.sample(true)
    if not origin then return nil end
    local ref='trail_'..namespace..'_'..serial
    if segment~=ref then after=0 end
    after=type(after)=='number' and after or 0
    local samples=P.array()
    for _,row in ipairs(rows) do if row.sequence>after then samples[#samples+1]=row end end
    return {ref=ref,sequence=sequence,start_heading_deg=round(math.deg(heading)%360),samples=samples,
        sparse=#samples>0 and samples[1].sequence>after+1,source='travelled_player_path'}
end
return M
