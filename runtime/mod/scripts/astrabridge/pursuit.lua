-- Range hysteresis for a single selected visible opponent. No attacks or actor
-- state changes: the player adapter supplies normal movement and stock uses.
local M={}
function M.new()return {holding=false,elapsed=0,travelled=0,status='following'}end
function M.step(s,c,dt)
    s.elapsed=s.elapsed+dt;s.travelled=s.travelled+(c.moved_m or 0)
    if s.reason then return false end
    if c.target_down then s.reason='target_down';s.status='stopped';return false end
    if c.target_lost then s.reason='target_lost';s.status='stopped';return false end
    if c.swimming then s.reason='swimming_requires_manual_control';s.status='stopped';return false end
    if not c.can_move then s.reason='cannot_act';s.status='stopped';return false end
    if c.ranged then s.holding=true
    elseif c.margin~=nil then
        if s.holding then s.holding=c.margin>.2 else s.holding=c.margin>=.45 end
    else s.holding=c.in_reach or false end
    s.status=s.holding and 'holding_range' or 'following'
    return not s.holding
end
function M.report(s,reason)
    return {direction='pursuit',travelled_m=math.floor(s.travelled*100+.5)/100,elapsed=s.elapsed,
        status=s.status,reason=s.reason or (reason=='completed' and 'following_finished' or reason or 'interrupted')}
end
return M
