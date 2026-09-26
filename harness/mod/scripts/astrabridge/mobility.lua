-- Movement abilities are derived only from effects on the player.
local types=require('openmw.types')
local core=require('openmw.core')
local self=require('openmw.self')
local util=require('openmw.util')
local M={}
function M.has(name)
    local id=core.magic and core.magic.EFFECT_TYPE and core.magic.EFFECT_TYPE[name]
    if not id or not types.Actor.activeEffects then return false end
    local effect=types.Actor.activeEffects(self):getEffect(id)
    return effect~=nil and effect.magnitude>0
end
function M.state()
    return {levitation=M.has('Levitate'),water_walking=M.has('WaterWalking'),
        water_breathing=M.has('WaterBreathing'),slow_fall=M.has('SlowFall')}
end
function M.waterLevel()
    if M.has('WaterWalking') and self.cell then return self.cell.waterLevel end
end
function M.surface(point)
    local level=M.waterLevel()
    if point and level and point.z<level then return util.vector3(point.x,point.y,level) end
    return point
end
function M.flags(flags)
    return flags.Walk+(M.has('WaterWalking') and (flags.Swim or 0) or 0)
end
return M
