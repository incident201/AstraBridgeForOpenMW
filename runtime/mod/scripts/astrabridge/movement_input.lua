-- Own only normal movement controls. In particular, never overwrite the stock
-- one-frame spell-use pulse, or the separately controlled camera turn deltas.
local M={}
function M.apply(controls,active,live,sneak,jump)
    controls.movement=live and (active.move or 0) or 0
    controls.sideMovement=live and (active.strafe or 0) or 0
    controls.run=live and (active.run or false) or false
    controls.jump=live and (jump or false) or false
    controls.sneak=sneak or false
end
return M
