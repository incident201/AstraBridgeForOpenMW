local camera=require('openmw.camera')
local I=require('openmw.interfaces')
local M={}
function M.apply()
    if not I.Camera or not I.Camera.disableModeControl then return end
    -- Scripted waiting is not physical keyboard input. The stock idle timer
    -- otherwise starts an orbit and decouples view direction from actor turns.
    I.Camera.disableModeControl('AstraBridge')
    if I.Camera.disableStandingPreview then I.Camera.disableStandingPreview('AstraBridge') end
    local mode=camera.getMode()
    if mode==camera.MODE.Vanity or mode==camera.MODE.Preview then
        local primary=I.Camera.getPrimaryMode and I.Camera.getPrimaryMode() or camera.MODE.FirstPerson
        camera.setMode(primary)
    end
end
return M
