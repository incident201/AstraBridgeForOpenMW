-- Private sequence guard, checked at dispatch and every simulation frame.
local M={}
function M.check(g,now,health)
    if not g then return nil end
    if health then
        local maximum=health.base and health.base+(health.modifier or 0) or health.maximum or 1
        if (g.stop_health_pct or 0)>0 and health.current<=maximum*g.stop_health_pct/100 then return 'health_low' end
        if g.stop_on_damage and g.health and health.current<g.health-.01 then return 'player_hurt' end
        -- Track healing too: any subsequent damage stops, even above initial HP.
        g.health=health.current
    end
    if g.deadline and now>=g.deadline then return 'sequence_time_limit' end
end
return M
