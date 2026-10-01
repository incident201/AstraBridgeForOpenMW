-- Progress means a new best remaining route distance, never just turning/moving.
local M={}
function M.update(state,elapsed,remaining,x,y,z)
    if not state.progress then
        state.progress={best=remaining,last=elapsed,started=elapsed,visits={},nextSample=elapsed}
    end
    local p=state.progress
    if remaining<p.best-7 then p.best=remaining;p.last=elapsed end -- 10 cm of actual route advancement
    if elapsed>=p.nextSample then
        p.nextSample=elapsed+.5
        local key=string.format('%d:%d:%d',math.floor(x/35),math.floor(y/35),math.floor(z/35))
        if key~=p.cell then
            p.visits[key]=(p.visits[key] or 0)+1;p.cell=key
            if p.visits[key]>=4 then return 'repeated_positions' end
        end
    end
    state.stalledSeconds=math.max(0,elapsed-p.last)
    if elapsed-p.started>2.5 and elapsed-p.last>1.5 then return 'no_route_progress' end
end
function M.recover(state,elapsed)
    if state.progress then state.progress.last=elapsed end
end
return M
