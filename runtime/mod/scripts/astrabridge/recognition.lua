-- Names are observations; durable knowledge belongs to the controller's DB.
local camera = require('openmw.camera')
local core = require('openmw.core')
local self = require('openmw.self')
local types = require('openmw.types')
local ui = require('openmw.ui')
local M = {}
local namespace, serial, dynamic = 'boot', 0, {}

function M.reset(epoch) namespace=epoch;serial=0 end

function M.kind(obj)
    for _,kind in ipairs({'Actor','Door','Container','Item','Activator'}) do
        if types[kind] and types[kind].objectIsInstance(obj) then return kind:lower() end
    end
end

local function instanceKey(obj)
    if obj.contentFile then
        -- OpenMW's FormId includes a load-order index. Keep only its local index
        -- and the source filename so reordering content doesn't rename objects.
        local hex=obj.id:match('0x(%x+)$')
        local index=hex and tonumber(hex,16)
        if index then
            return 'content:'..obj.contentFile..':'..string.format('%x',index%0x1000000)..':'..obj.recordId
        end
        return nil -- Unknown identity format must never match another instance.
    end
    local entry=dynamic[obj.id]
    if not entry then
        serial=serial+1
        entry={object=obj,token='dynamic:'..namespace..':'..serial}
        dynamic[obj.id]=entry
    end
    return entry.token
end

-- Only instance tokens enter saves, never names or descriptions. A restored
-- object reference is remapped by OpenMW; newly spawned objects after a load
-- receive new tokens even when the engine reuses a dynamic FormId.
function M.save()
    local entries={}
    for _,entry in pairs(dynamic) do
        -- Unloaded cells make references temporarily invalid. Serializing their
        -- identity is still supported and must not forget a previously met actor.
        entries[#entries+1]=entry
    end
    return entries
end

function M.load(entries)
    dynamic={}
    for _,entry in ipairs(type(entries)=='table' and entries or {}) do
        if type(entry.token)=='string' and entry.token:match('^dynamic:') then
            local ok,id=pcall(function() return entry.object.id end)
            if ok and id then dynamic[id]=entry end
        end
    end
end

function M.detailsVisible(g)
    -- The real focus target also honours engine overrides and special reach.
    if ui._astraIsActivationTarget and ui._astraIsActivationTarget(g.obj) then return true end
    local limit=core.getGMST('iMaxActivateDist')
    local actor=types.Actor.objectIsInstance(g.obj)
    local telekinesis=not actor
    if types.Door and types.Door.objectIsInstance(g.obj) and types.Door.isTeleport(g.obj) then
        telekinesis=types.Lockable.isLocked(g.obj) or types.Lockable.getTrapSpell(g.obj)~=nil
    end
    if telekinesis then
        local effect=types.Actor.activeEffects(self):getEffect('telekinesis')
        -- World::feetToGameUnits rounds 21 1/3 units per foot up to 22.
        if effect then limit=limit+math.max(0,effect.magnitude)*22 end
    end
    local cameraDistance=camera.getThirdPersonDistance and camera.getThirdPersonDistance() or 0
    return math.max(0,g.distance-cameraDistance)<=limit
end

function M.fields(g)
    local obj=g.obj
    local kind=g.kind or M.kind(obj)
    local out={kind=kind,details_visible=M.detailsVisible(g),_recognition_key=instanceKey(obj)}
    if kind=='actor' then
        out.actor_kind=types.NPC and types.NPC.objectIsInstance(obj) and 'npc' or 'creature'
    end
    if out.details_visible then
        local rec=obj.type.record(obj)
        if rec and rec.name and rec.name~='' then out.name=rec.name;out.name_source='observed' end
    end
    return out
end
return M
