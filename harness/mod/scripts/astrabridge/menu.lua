local core = require('openmw.core')
local menu = require('openmw.menu')
local storage = require('openmw.storage')
local P = require('scripts.astrabridge.protocol')
local bus = storage.playerSection('AstraBridge')
bus:setLifeTime(storage.LIFE_TIME.GameSession)
local session, lastId, lastReply = nil, 0, nil
local nextPoll = 0
local pending
local refs, refSerial = {}, 0
local function checkpointKey(dir,slot)
    -- Opaque, stable slot identity. creationTime is sampled before writing, but
    -- after restart OpenMW derives it from the file timestamp (slightly later).
    local a,b=2166136261,5381
    local text=dir..'/'..slot
    for i=1,#text do
        local byte=text:byte(i)
        a=(a*65599+byte)%4294967296;b=(b*131+byte)%4294967296
    end
    return string.format('checkpoint_%08x%08x',a,b)
end
local function state()
    local s = menu.getState()
    if s == menu.STATE.Running then return 'running' end
    if s == menu.STATE.Ended then return 'ended' end
    return 'menu'
end
local function saves()
    local list = P.array()
    refs = {}
    for dir, slots in pairs(menu.getAllSaves()) do
        for slot, info in pairs(slots) do
            refSerial = refSerial + 1
            local ref = 'save_' .. (session or 'boot'):sub(1,8) .. '_' .. refSerial
            refs[ref] = {dir=dir, slot=slot}
            list[#list+1] = {ref=ref, description=info.description,
                checkpoint_key=checkpointKey(dir,slot),
                time_played_seconds=info.timePlayed,
                player_name=info.playerName, player_level=info.playerLevel,
                created=info.creationTime}
        end
    end
    table.sort(list, function(a,b) return a.created > b.created end)
    return list
end
local function reply(cmd, result, err)
    lastReply = {cmd=cmd, result=result, error=err}
    P.reply(cmd, result, err)
end
local function dispatch(cmd)
    if cmd.op == 'ping' then
        reply(cmd, {state=state(), api_revision=core.API_REVISION})
    elseif cmd.op == 'saves' then
        reply(cmd, {saves=saves()})
    elseif cmd.op == 'save' then
        if state() ~= 'running' or not bus:get('can_save') then
            reply(cmd, nil, 'save_unavailable'); return
        end
        assert(type(cmd.args.description) == 'string' and #cmd.args.description <= 160)
        -- Omitting slotName creates a new save; never overwrites an existing one.
        menu.saveGame(cmd.args.description)
        reply(cmd, {saves=saves()})
    elseif cmd.op == 'new_game' or cmd.op == 'load' then
        local target
        if cmd.op == 'load' then
            target = refs[cmd.args.ref]
            if not target then reply(cmd, nil, 'stale_save_ref'); return end
        end
        bus:set('ready', false)
        bus:set('request', nil)
        bus:set('response', nil)
        bus:set('can_save', false)
        if target then menu.loadGame(target.dir, target.slot) else menu.newGame() end
        pending = {cmd=cmd, lifecycle=true, deadline=core.getRealTime()+90}
    elseif cmd.op == 'quit' then
        reply(cmd, {state='quitting'})
        menu.quit()
    elseif state() ~= 'running' then
        if cmd.op == 'observe' or cmd.op == 'stop' then
            reply(cmd, {state=state(), paused=true, ui_mode='MainMenu'})
        else reply(cmd, nil, 'no_player') end
    else
        bus:set('response', nil)
        bus:set('request', cmd)
        local motor=({act=true,look=true,focus=true,approach=true,move_local=true,walk=true,go=true,evade=true,track=true,lock=true,strike=true,cast=true,chain=true})[cmd.op]
        pending = {cmd=cmd, deadline=core.getRealTime()+(motor and 55 or 20)}
    end
end
local function onFrame()
    local now = core.getRealTime()
    if pending then
        if pending.lifecycle and bus:get('ready') then
            reply(pending.cmd, {state=state(), paused=true})
            pending = nil
        elseif not pending.lifecycle then
            local r = bus:getCopy('response')
            if r and r.id == pending.cmd.id and r.session == pending.cmd.session then
                reply(pending.cmd, r.result, r.error)
                pending = nil
            end
        end
        if pending and now > pending.deadline then
            bus:set('cancel', true)
            if state() == 'running' then core.sendGlobalEvent('AstraPause', {}) end
            reply(pending.cmd, nil, 'game_operation_timeout')
            pending = nil
        end
    end
    if now < nextPoll then return end
    nextPoll = now + 0.025
    local ok, cmd = pcall(P.read)
    if not ok or not cmd then return end
    if session ~= cmd.session then
        session, lastId, lastReply = cmd.session, 0, nil
        bus:set('session',session)
        bus:set('cancel', true)
    end
    if cmd.id <= lastId then return end
    if pending then
        if cmd.op ~= 'stop' then return end
        bus:set('cancel', true)
        reply(pending.cmd, nil, 'cancelled')
        pending = nil
    end
    lastId = cmd.id
    local good = pcall(dispatch, cmd)
    if not good then reply(cmd, nil, 'operation_failed') end
end
return {engineHandlers={onFrame=onFrame}}
