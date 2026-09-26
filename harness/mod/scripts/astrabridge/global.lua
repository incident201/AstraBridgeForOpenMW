local world = require('openmw.world')
local TAG = 'AstraBridge'
local activePlayer
local generation = 0
return {
    engineHandlers = {
        onPlayerAdded = function(player)
            activePlayer = player
            generation = generation + 1
            world.pause(TAG)
            player:sendEvent('AstraReset', {generation=generation})
        end,
    },
    eventHandlers = {
        AstraPause = function(data)
            world.pause(TAG)
            if activePlayer then activePlayer:sendEvent('AstraPaused', data) end
        end,
        AstraResume = function(data)
            -- Unpause only our own tag. UI and other mods retain their pauses.
            world.unpause(TAG)
            if activePlayer then activePlayer:sendEvent('AstraResumed', data) end
        end,
    },
}
