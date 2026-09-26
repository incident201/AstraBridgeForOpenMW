-- Human-readable mechanics for effects already known to, or affecting, the player.
-- No effect IDs or per-frame random magnitudes leave this helper.
local M={}
function M.healthKind(id,ids)
    if not id or not ids then return nil end
    for _,name in ipairs({'DamageHealth','Poison','FireDamage','FrostDamage','ShockDamage','SunDamage'}) do
        if ids[name]==id then return 'damage' end
    end
    if ids.DrainHealth==id then return 'temporary_reduction' end
    if ids.RestoreHealth==id then return 'healing' end
    if ids.FortifyHealth==id then return 'temporary_bonus' end
end
return M
