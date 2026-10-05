local core = require('openmw.core')
local self = require('openmw.self')
local types = require('openmw.types')
local input = require('openmw.input')
local async = require('openmw.async')
local storage = require('openmw.storage')
local I = require('openmw.interfaces')
local P = require('scripts.astrabridge.protocol')
local Scene = require('scripts.astrabridge.scene')
local Combat = require('scripts.astrabridge.combat')
local hasAnimation, animation = pcall(require,'openmw.animation')
local Evasion = require('scripts.astrabridge.evasion')
local Trajectory = require('scripts.astrabridge.trajectory')
local EffectFacts=require('scripts.astrabridge.effect_facts')
local Mobility=require('scripts.astrabridge.mobility')
local Airborne=require('scripts.astrabridge.airborne')
local MovementInput=require('scripts.astrabridge.movement_input')
local Pursuit=require('scripts.astrabridge.pursuit')
local Ballistics=require('scripts.astrabridge.ballistics')
local directMovement=I.Controls and I.Controls.overrideMovementControls~=nil
local Space=require('scripts.astrabridge.space')
local Turning=require('scripts.astrabridge.turning')
local camera = require('openmw.camera')
local ui = require('openmw.ui')
local util = require('openmw.util')
local bus = storage.playerSection('AstraBridge')
local A, Player = types.Actor, types.Player
local Terrain=A.getPathfindingAgentBounds and require('scripts.astrabridge.terrain')
local refs, serial, epoch = {}, 0, 0
local ownedRefs={}
local Guards=require('scripts.astrabridge.guards')
local requestKey, pending, active
local pauseSerial, pauseAck, settle = 0, -1, 0
local ready = false
local lastFrame = 0
local wasRunning = false
local desiredFov=bus:get('horizontal_fov') or 100
local targetLock
local routes={}
local walkingRoute
local pausedSneak=false
local manualActive=false
local uiMessages,seenMessages = P.array(),{}
local seenNotifications={}
local modalOpen=false
local motorOperations={jump=true,air_move=true,act=true,look=true,focus=true,approach=true,move_local=true,walk=true,go=true,
    fly=true,swim=true,evade=true,track=true,lock=true,strike=true,cast=true,chain=true,interact=true,wait_until=true}
local function lockState()
    if not targetLock then return {status='unlocked'} end
    local out=Scene.identity(targetLock.ref)
    out.status=targetLock.status;out.ref=targetLock.ref
    return out
end
local function lockedTarget()
    if not targetLock or targetLock.status=='down' then return nil end
    if targetLock.cell~=Space.key(self.cell) then targetLock.status='location_changed';return nil end
    local g=Scene.track and Scene.track(targetLock.ref) or Scene.resolve(targetLock.ref,true)
    if not g then targetLock.status='lost';return nil end
    if A.isDead(g.obj) then targetLock.status='down';return nil end
    targetLock.status='locked'
    return g
end
local allowedTriggers = {Activate=true, ToggleWeapon=true, ToggleSpell=true,
    Jump=true, Inventory=true, Journal=true}

local function windowAllowed(name)
    local w = I.UI.getWindowsForMode(I.UI.MODE.Interface)
    return w[name] ~= nil
end
local function ownHealth()
    return A.stats and A.stats.dynamic and A.stats.dynamic.health(self).current
end
local function controlsAllowed()
    return Player.getControlSwitch(self, Player.CONTROL_SWITCH.Controls)
end
local function round(n) return math.floor(n + 0.5) end
local function plain(text) return (text:gsub('@(.-)#','%1')) end
local function namespace()return (bus:get('session') or 'test'):sub(1,8)..'_'..epoch end
local function uiState()
    if not ui._astraUiSnapshot then return {supported=false,elements=P.array()} end
    local result=ui._astraUiSnapshot(namespace());result.supported=true
    result.blocked=result.revision=='non_gameplay_ui'
    result.revision=namespace()..'_'..result.revision
    if result.document then result.document.ref='document_'..namespace()..'_'..result.document.ref:sub(10) end
    for _,e in ipairs(result.elements) do
        e.ref='ui_'..namespace()..'_'..e.ref:sub(4)
        if e.instance then e.instance='instance_'..namespace()..'_'..e.instance end
    end
    -- Codes come from the message's original GMST token before translation.
    -- A generic name-entry warning is a potion warning only in the alchemy UI.
    for _,e in ipairs(result.elements) do
        if e.notice=='potion_name_required' and I.UI.getMode()~='Alchemy' then e.notice=nil end
    end
    local runs={}
    for _,e in ipairs(result.elements) do
        if e.rect and e.role~='button' and e.role~='item' and e.role~='item_slot' and e.role~='drop_target' and e.role~='slider' then runs[#runs+1]=e end
    end
    table.sort(runs,function(a,b)
        if a.rect[2]~=b.rect[2] then return a.rect[2]<b.rect[2] end
        return a.rect[1]<b.rect[1]
    end)
    local text,lastY,lastRight,lastPanel='',-10000,0,nil
    for _,e in ipairs(runs) do
        local same=math.abs(e.rect[2]-lastY)<=2
        local gap=e.rect[1]-lastRight
        if text~='' then text=text..(same and (e.panel=='rich_text' and lastPanel=='rich_text' and gap>=-2 and gap<=5 and '' or ' | ') or '\n') end
        text=text..e.text;lastY=e.rect[2];lastRight=e.rect[1]+e.rect[3];lastPanel=e.panel
    end
    result.text=result.dialogue and result.dialogue.text or text
    if result.dialogue then
        result.dialogue.topics=P.array()
        for _,e in ipairs(result.elements) do
            if e.panel=='dialogue_topics' then result.dialogue.topics[#result.dialogue.topics+1]=e end
        end
    end
    return result
end
local function ref(value, kind)
    if kind=='item' and ownedRefs[value.id] and refs[ownedRefs[value.id]] then return ownedRefs[value.id] end
    serial = serial + 1
    local id = kind .. '_' .. namespace() .. '_' .. serial
    refs[id] = {value=value, kind=kind}
    if kind=='item' then ownedRefs[value.id]=id end
    return id
end
local function invalidate()
    local kept={}
    for id,r in pairs(refs) do if r.kind=='item' and r.value:isValid() then kept[id]=r end end
    refs=kept
end
local function stats(detailed)
    local out = {}
    if not windowAllowed('Stats') then return out end
    for _, name in ipairs({'health','magicka','fatigue'}) do
        local v = A.stats.dynamic[name](self)
        -- Native stat labels truncate positive fractional values.
        out[name] = {current=math.floor(v.current), maximum=math.floor(v.base + v.modifier)}
    end
    out.level = A.stats.level(self).current
    if windowAllowed('Inventory') then out.gold=A.inventory(self):countOf('gold_001') end
    if not detailed then return out end
    out.attributes = {}
    out.attribute_details=P.array()
    for _, name in ipairs({'strength','intelligence','willpower','agility','speed','endurance','personality','luck'}) do
        local value=A.stats.attributes[name](self)
        local rec=core.stats and core.stats.Attribute.records[name]
        out.attributes[name] = math.floor(value.modified)
        out.attribute_details[#out.attribute_details+1]={name=rec and rec.name or name,
            value=math.floor(value.modified),base=value.base and math.floor(value.base),
            modifier=value.modifier,damage=value.damage}
    end
    out.skills=P.array()
    if types.NPC.stats.skills then
        for key,fn in pairs(types.NPC.stats.skills) do
            if type(fn)=='function' then
                local value=fn(self)
                local rec=core.stats and core.stats.Skill.records[key]
                out.skills[#out.skills+1]={name=rec and rec.name or key,value=math.floor(value.modified),
                    base=value.base and math.floor(value.base),modifier=value.modifier,damage=value.damage,
                    progress_percent=round(value.progress*100)}
            end
        end
        table.sort(out.skills,function(a,b)return a.name<b.name end)
    end
    return out
end
local function bodyState()
    if not A.getStance then return {} end
    local body=ui._astraPlayerState and ui._astraPlayerState() or {}
    local stance=A.getStance(self)
    body.stance=stance==A.STANCE.Weapon and 'weapon' or stance==A.STANCE.Spell and 'spell' or 'nothing'
    body.on_ground=A.isOnGround(self)
    body.swimming=A.isSwimming(self)
    body.can_move=A.canMove(self)
    body.controls_enabled=controlsAllowed()
    body.looking_enabled=Player.getControlSwitch(self,Player.CONTROL_SWITCH.Looking)
    body.jumping_enabled=Player.getControlSwitch(self,Player.CONTROL_SWITCH.Jumping)
    body.dead=A.isDead(self)
    for k,v in pairs(Mobility.state()) do body[k]=v end
    for k,v in pairs(Airborne.state(body.on_ground,body.swimming,body.levitation)) do body[k]=v end
    if hasAnimation and animation.getActiveGroup then
        local ok,recovering=pcall(function()
            for _,part in ipairs({animation.BONE_GROUP.LowerBody,animation.BONE_GROUP.Torso,
                                  animation.BONE_GROUP.LeftArm,animation.BONE_GROUP.RightArm}) do
                if Combat.isRecoveryGroup(animation.getActiveGroup(self,part)) then return true end
            end
            return false
        end)
        if ok then body.recovering=recovering end
    end
    local weapon=A.getEquipment(self,A.EQUIPMENT_SLOT.CarriedRight)
    if weapon then body.weapon=weapon.type.record(weapon).name end
    local spell=A.getSelectedSpell(self)
    if spell then body.selected_spell=spell.name end
    local enchanted=A.getSelectedEnchantedItem(self)
    if enchanted then body.selected_enchantment=enchanted.type.record(enchanted).name end
    return body
end
local function effectList(effects)
    local list=P.array()
    for _,e in ipairs(effects or {}) do
        list[#list+1]={name=e.effect.name,description=plain(e.effect.description or ''),harmful=e.effect.harmful,
            health_effect=EffectFacts.healthKind(e.effect.id,core.magic and core.magic.EFFECT_TYPE),range=({[0]='self',[1]='touch',[2]='target'})[e.range],
            magnitude_min=e.magnitudeMin,magnitude_max=e.magnitudeMax,duration=e.duration,area=e.area}
    end
    return list
end
local function ammunition()
    if not types.Weapon then return nil end
    local held=A.getEquipment(self,A.EQUIPMENT_SLOT.CarriedRight)
    if not held or not types.Weapon.objectIsInstance(held) then return nil end
    local kind=types.Weapon.record(held).type
    local w=types.Weapon.TYPE
    if kind==w.MarksmanThrown then return held.recordId,types.Weapon.record(held).name end
    if kind~=w.MarksmanBow and kind~=w.MarksmanCrossbow then return nil end
    local ammo=A.getEquipment(self,A.EQUIPMENT_SLOT.Ammunition)
    local expected=kind==w.MarksmanBow and w.Arrow or w.Bolt
    if ammo and types.Weapon.objectIsInstance(ammo) and types.Weapon.record(ammo).type==expected then
        return ammo.recordId,types.Weapon.record(ammo).name
    end
end
local function combatInfo()
    if not ui._astraCombatInfo then return {supported=false} end
    local info=ui._astraCombatInfo();info.supported=true
    if info.weapon_info and info.weapon_info.kind=='ranged' then
        local id,name=ammunition()
        info.weapon_info.ammunition_count=id and A.inventory(self):countOf(id) or 0
        info.weapon_info.ammunition_name=name
        if A.isSwimming(self) and ui._astraPlayerState and ui._astraPlayerState().submerged then
            -- OpenMW consumes ammunition but discards a projectile launched
            -- underwater. Spending alone would misleadingly confirm a shot.
            info.weapon_info.available=false
            info.weapon_info.unavailable_reason='underwater_ranged_unavailable'
        end
    end
    if info.castable and info.castable.name then
        local spell=A.getSelectedSpell(self)
        local item=A.getSelectedEnchantedItem(self)
        local record=spell
        if item then local id=item.type.record(item).enchant;record=id and core.magic.enchantments.records[id] end
        info.castable.effects=effectList(record and record.effects)
        if info.castable.charge_current then info.castable.charge_current=math.floor(info.castable.charge_current*100+.5)/100 end
    end
    if info.weapon_info and info.weapon_info.reach_m then info.weapon_info.reach_m=math.floor(info.weapon_info.reach_m*100+.5)/100 end
    return info
end
local function activeEffects()
    local result=P.array()
    if not windowAllowed('Magic') or not A.activeSpells then return result end
    for _,spell in pairs(A.activeSpells(self)) do
        local row={name=spell.name,temporary=spell.temporary,from_equipment=spell.fromEquipment,effects=P.array()}
        for _,e in pairs(spell.effects) do
            local record=core.magic and core.magic.effects and core.magic.effects.records[e.id]
            row.effects[#row.effects+1]={name=e.name,magnitude_min=e.minMagnitude,magnitude_max=e.maxMagnitude,
                description=record and plain(record.description or ''),harmful=record and record.harmful,
                health_effect=EffectFacts.healthKind(e.id,core.magic and core.magic.EFFECT_TYPE),
                duration=e.duration,permanent=e.durationLeft==nil,
                remaining_seconds=e.durationLeft and math.floor(e.durationLeft*10+.5)/10}
            local detail=row.effects[#row.effects]
            if e.affectedAttribute and core.stats then detail.affected_attribute=core.stats.Attribute.records[e.affectedAttribute].name end
            if e.affectedSkill and core.stats then detail.affected_skill=core.stats.Skill.records[e.affectedSkill].name end
        end
        result[#result+1]=row
    end
    return result
end
local function observation(args)
    local out = {state='running', paused=core.isWorldPaused(), pause_backend=ui._astraPause and 'synchronous' or 'global_event',
        movement_backend=directMovement and 'actor_controls' or 'input_bindings',ui_mode=I.UI.getMode() or 'Gameplay',
        epoch=epoch, frame=lastFrame, stats=stats(), available=P.array(), text_source='screenshot',
        orientation=Scene.orientation(),location=Space.label(self.cell,core.regions and core.regions.records),ui=uiState(),target_lock=lockState(),messages=uiMessages}
    if out.ui.supported then out.text_source='native_ui' end
    out.simulation_seconds=core.getSimulationTime()
    out.game_time_seconds=core.getGameTime()
    if windowAllowed('Inventory') then
        out._inventory_counts={}
        for _,obj in ipairs(A.inventory(self):getAll()) do
            local name=obj.type.record(obj).name
            out._inventory_counts[name]=(out._inventory_counts[name] or 0)+obj.count
        end
    end
    if windowAllowed('Magic') then out.journal_count=#Player.journal(self).journalTextEntries end
    out.body=bodyState()
    out.trajectory=Trajectory.report(args and args._trail_after,args and args._trail_segment)
    out._atlas_frame=Trajectory.frame()
    out._atlas_travel=Trajectory.flush()
    out.combat=combatInfo()
    out.effects=activeEffects()
    if not I.UI.getMode() and not out.ui.modal then
        out.scene=Scene.observe()
        if Terrain then out.terrain=Terrain.observe() end
    end
    if windowAllowed('Inventory') then out.available[#out.available+1] = 'inventory' end
    if windowAllowed('Stats') then out.available[#out.available+1] = 'stats' end
    if windowAllowed('Magic') then
        out.available[#out.available+1] = 'spells'
        out.available[#out.available+1] = 'journal'
        out.available[#out.available+1] = 'conversations'
        out.available[#out.available+1] = 'effects'
    end
    if out.combat.supported then out.available[#out.available+1]='combat' end
    return out
end
local function inspect(args)
    if args.view=='character' then
        if not windowAllowed('Stats') then return nil,'view_unavailable' end
        local own=types.NPC.record(self)
        local race=types.NPC.races.records[own.race]
        local class=types.NPC.classes.records[own.class]
        local sign=Player.birthSigns.records[Player.getBirthSign(self)]
        local out={player_name=own.name,race=race.name,class=class.name,birth_sign=sign and sign.name,
            stats=stats(true),body=bodyState(),effects=activeEffects(),combat=combatInfo(),
            location=Space.label(self.cell,core.regions and core.regions.records),paused=core.isWorldPaused(),
            bounty=Player.getCrimeLevel(self),reputation=types.NPC.stats.reputation(self).current}
        if windowAllowed('Inventory') then
            out.carried_weight=round(A.getEncumbrance(self));out.capacity=round(A.getCapacity(self))
            out.overencumbered=out.carried_weight>out.capacity
        end
        return out
    end
    if args.view=='combat' then return {combat=combatInfo()} end
    if args.view=='effects' then return {effects=activeEffects()} end
    if args.view == 'stats' then return {stats=stats(true)} end
    if args.view == 'inventory' then
        if not windowAllowed('Inventory') then return nil, 'view_unavailable' end
        invalidate()
        local items = P.array()
        for _, obj in ipairs(A.inventory(self):getAll()) do
            -- No record or object escapes this projection. Unknown ingredient effects stay unknown.
            local rec = obj.type.record(obj)
            items[#items+1] = {ref=ref(obj, 'item'), name=rec.name,
                count=obj.count, equipped=A.hasEquipped(self, obj)}
            local row=items[#items]
            for _,kind in ipairs({'Weapon','Armor','Clothing','Book','Potion','Ingredient','Apparatus','Repair','Lockpick','Probe','Light','Miscellaneous'}) do
                if types[kind] and types[kind].objectIsInstance(obj) then row.kind=kind:lower();break end
            end
            if ui._astraOwnedItemInfo then for k,v in pairs(ui._astraOwnedItemInfo(obj,namespace())) do row[k]=v end end
            if row.instance then row.instance='instance_'..namespace()..'_'..row.instance end
        end
        return {items=items, carried_weight=round(A.getEncumbrance(self)), capacity=round(A.getCapacity(self))}
    elseif args.view == 'spells' then
        if not windowAllowed('Magic') then return nil, 'view_unavailable' end
        invalidate()
        local list = P.array()
        local selected = A.getSelectedSpell(self)
        for _, spell in pairs(A.spells(self)) do
            if spell.type == core.magic.SPELL_TYPE.Spell or spell.type == core.magic.SPELL_TYPE.Power then
                local row={ref=ref(spell,'spell'), name=spell.name,
                    selected=selected ~= nil and selected.id == spell.id,effects=P.array()}
                if ui._astraSpellInfo then
                    for k,v in pairs(ui._astraSpellInfo(spell.id)) do row[k]=v end
                elseif not spell.isAutocalc then row.cost=spell.cost end
                row.effects=effectList(spell.effects)
                list[#list+1]=row
            end
        end
        return {spells=list}
    elseif args.view == 'journal' then
        if not windowAllowed('Magic') then return nil, 'view_unavailable' end
        local page = P.number(args.page, 0, 100000, 0)
        assert(page % 1 == 0)
        local entries = Player.journal(self).journalTextEntries
        local result = P.array()
        for i=page*30+1, math.min(#entries, (page+1)*30) do
            local entry = entries[i]
            result[#result+1] = {text=plain(entry.text), day=entry.day, month=entry.month, day_of_month=entry.dayOfMonth}
        end
        return {entries=result, page=page, total=#entries}
    elseif args.view=='conversations' then
        if not windowAllowed('Magic') then return nil,'view_unavailable' end
        local topics=Player.journal(self).topics
        local result=P.array()
        if not args.topic then
            for _,t in pairs(topics) do result[#result+1]={name=t.name} end
            table.sort(result,function(a,b)return a.name<b.name end)
            return {topics=result}
        end
        local topic=topics[args.topic]
        if not topic then return nil,'unknown_topic' end
        local page=P.number(args.page,0,100000,0)
        for i=page*30+1,math.min(#topic.entries,(page+1)*30) do
            local entry=topic.entries[i]
            result[#result+1]={text=plain(entry.text),speaker=entry.actor}
        end
        return {name=topic.name,entries=result,page=page,total=#topic.entries}
    end
    return nil, 'unknown_view'
end

local function clearInput()
    active = nil
    self.controls.movement, self.controls.sideMovement = 0, 0
    self.controls.jump, self.controls.sneak = false, pausedSneak
    self.controls.run=false
    self.controls.use = self.ATTACK_TYPE.NoAttack
    self.controls.yawChange, self.controls.pitchChange = 0, 0
end
local function pause(cmd, result, err)
    if result and pending and pending.evade then
        if pending.evadeUnit and Space.key(self.cell)==pending.start.cell then
            local delta=self.position-pending.evadePosition
            pending.evade.travelled=pending.evade.travelled+math.max(0,delta.x*pending.evadeUnit.x+delta.y*pending.evadeUnit.y)/Scene.unitsPerMeter
        end
        if pending.chain then
            result.movement=Evasion.report(pending.evade)
            result.movement.reason=pending.evade.reason or result.reason or 'interrupted'
        else
            for k,v in pairs(Evasion.report(pending.evade)) do if result[k]==nil then result[k]=v end end
        end
    end
    if result and pending and pending.pursuit then
        if pending.start and Space.key(self.cell)==pending.start.cell then
            pending.pursuit.travelled=pending.pursuit.travelled+(self.position-pending.pursuit.position):length()/Scene.unitsPerMeter
            pending.pursuit.position=self.position
        end
        pending.pursuit.elapsed=pending.chain.elapsed
        result.movement=Pursuit.report(pending.pursuit,result.reason)
        if pending.pursuit.nav then result.movement.navigation=require('scripts.astrabridge.navigation').report(pending.pursuit.nav) end
    end
    if result and pending and pending.aerial then
        if Space.key(self.cell)==pending.start.cell then
            Airborne.update(pending.aerial,A.isOnGround(self),A.isSwimming(self),self.position.z,ownHealth())
        end
        result.aerial=Airborne.report(pending.aerial,Scene.unitsPerMeter)
    end
    if result and pending and pending.start then
        result.motion=Scene.report(pending.start)
        result.body=bodyState()
        result.elapsed=result.elapsed or pending.elapsed
    end
    if result and pending and pending.navigator then
        result.navigation=require('scripts.astrabridge.navigation').report(pending.navigator)
    end
    if result and pending and pending.walkRef then result.ref=pending.walkRef end
    clearInput()
    pauseSerial = pauseSerial + 1
    settle = 0
    local expected=pending and pending.expected
    local finalPose=pending and pending.start
    local finalNavigator=pending and pending.navigator
    local finalCombatBase=pending and pending.combat and pending.resources
    local finalChainBase=pending and pending.chain and pending.chain.initial
    local finalAmmoRecord=pending and pending.ammoRecord
    local combatTail=pending and pending.finishedCombatResult~=nil
    pending = {cmd=cmd, phase='pausing', token=pauseSerial, result=result, error=err,expected=expected,
        finalAerial=pending and pending.aerial,finalPose=finalPose,finalNavigator=finalNavigator,finalCombatBase=finalCombatBase,finalChainBase=finalChainBase,
        combatTail=combatTail,finalAmmoRecord=finalAmmoRecord,pausePose=finalPose and Scene.pose() or nil}
    -- Optional synchronous main-thread adapter; the global event remains the
    -- acknowledgement/fallback and only our own pause tag is affected.
    if ui._astraPause and ui._astraPause() and wasRunning then
        wasRunning=false
        P.emit({version=1,session=bus:get('session'),event='simulation',active=false})
    end
    core.sendGlobalEvent('AstraPause', {token=pauseSerial})
end
local function finishStep(p,result)
    if p.requestedAttack or p.attack then
        active={move=0,strafe=0,attack=false}
        self.controls.use=self.ATTACK_TYPE.NoAttack
        self.controls.movement,self.controls.sideMovement=0,0
        p.phase='releasing';p.result=result;p.releaseFrame=lastFrame
    else pause(p.cmd,result) end
end
local function resources(ammoRecord)
    local info=combatInfo();local c=info.castable or {}
    return {health=A.stats.dynamic.health(self).current,magicka=A.stats.dynamic.magicka(self).current,
        charge=c.charge_current,count=c.kind=='scroll' and c.count or nil,
        ammunition=ammoRecord and A.inventory(self):countOf(ammoRecord)
            or info.weapon_info and info.weapon_info.kind=='ranged' and info.weapon_info.ammunition_count or nil}
end
local function spendingKind(kind,selected)
    if kind=='strike' and selected and selected.kind=='ranged' then return 'ammunition' end
    if kind=='cast' and selected then
        if selected.kind=='scroll' then return 'count' end
        if (selected.cost or 0)>0 then return selected.kind=='enchantment' and 'charge' or 'magicka' end
    end
end
local function resourceDelta(base,now,aggregate)
    local result={}
    for k,v in pairs(base) do
        if not aggregate or k=='health' or k=='magicka' then
            local current=now[k]
            if k=='count' and current==nil then current=0 end
            if current~=nil then result[k..'_change']=math.floor((current-v)*100+.5)/100 end
        end
    end
    return result
end
local beginChainStep
local function finishCombat(p,reason)
    if p.finishedCombatResult then
        local result=p.finishedCombatResult
        if reason then result.reason=reason;result.outcome='interrupted' end
        result.elapsed=p.chain.elapsed
        local now=resources()
        result.resources={health_change=math.floor((now.health-p.chain.initial.health)*100+.5)/100,
            magicka_change=math.floor((now.magicka-p.chain.initial.magicka)*100+.5)/100}
        pause(p.cmd,result);return
    end
    if reason then Combat.abort(p.combat,reason) end
    local result=Combat.report(p.combat);result.paused=true
    result.operation=p.combat.kind
    if p.castableName then result.name=p.castableName end
    if p.aimAssistance then result.aim_assistance=p.aimAssistance end
    if p.aimFlight then result.estimated_flight_seconds=math.floor(p.aimFlight*100+.5)/100 end
    if p.aimNote then result.aim_note=p.aimNote end
    local now=resources(p.ammoRecord);result.resources={}
    for k,v in pairs(p.resources) do
        local current=now[k]
        if k=='count' and current==nil then current=0 end
        if current~=nil then result.resources[k..'_change']=math.floor((current-v)*100+.5)/100 end
    end
    result.messages=P.array()
    for _,m in ipairs(uiMessages) do
        if m.frame>=p.firstFrame then
            result.messages[#result.messages+1]=m
            if p.combat.kind=='cast' and m.notice=='spell_failed' then result.cast_outcome='failed' end
        end
    end
    if p.chain then
        result.paused=false -- no pause was requested between these steps
        p.chain.results[#p.chain.results+1]=result
        if result.reason=='completed' then p.chain.completed=p.chain.completed+1
        elseif result.reason=='target_down' and result.attempted then p.chain.completed=p.chain.completed+1 end
        if result.reason=='completed' and p.chain.index<#p.chain.plan and p.chain.elapsed<p.chain.limit then
            beginChainStep(p,p.chain.index+1)
            return
        end
        local reason=result.reason
        if reason=='completed' and p.chain.index<#p.chain.plan then reason='chain_time_limit' end
        result={paused=true,reason=reason,elapsed=p.chain.elapsed,steps=p.chain.results,
            completed_actions=p.chain.completed,total_actions=#p.chain.plan,
            outcome=reason=='completed' and 'chain_completed' or reason=='target_down' and 'target_down' or 'interrupted',
            resources={health_change=math.floor((now.health-p.chain.initial.health)*100+.5)/100,
                magicka_change=math.floor((now.magicka-p.chain.initial.magicka)*100+.5)/100}}
    end
    if p.chain and p.evade and not p.evade.reason and result.reason=='completed' then
        p.finishedCombatResult=result
        active.attack=false
        return
    end
    pause(p.cmd,result)
end
local function interruptForModal()
    local p=pending
    -- UI queries/choices must still finish while the modal is open. Only an
    -- action that resumed simulation (or is settling its result) is interrupted.
    if not p or not p.cmd or not (p.start or p.finalPose) then return end
    if p.phase=='pausing' then
        if p.result and not p.error and p.result.reason~='cancelled' and p.result.reason~='player_down' then
            p.result.reason='ui_input_required';p.result.outcome='interrupted'
        end
        clearInput() -- Do not restart the pause handshake on every modal frame.
    elseif p.combat then
        finishCombat(p,'ui_input_required')
    else
        local result=p.phase=='releasing' and p.result or {}
        result.paused=true;result.reason='ui_input_required';result.outcome='interrupted'
        result.elapsed=result.elapsed or p.elapsed or 0
        pause(p.cmd,result)
    end
end
beginChainStep=function(p,index)
    local step=p.chain.plan[index]
    local previous=p.combat
    local continued=previous and previous.kind==step.op and previous.reason=='completed' and previous.released
    p.chain.index=index;p.combat=Combat.new(step.op,step.op=='wait' and step.seconds or step.charge,continued)
    p.resources=resources();p.firstFrame=lastFrame;p.target=nil;p.rangeCheck=nil
    p.ammoRecord=nil;p.spendKind=nil;p.pursuitRangeKind=nil
    p.expectedWeapon=nil;p.evidenceResources=nil
    p.ranged=false;p.ballistic=nil;p.aimAssistance=nil;p.aimFlight=nil;p.aimNote=nil
    p.selectionReady=false;p.selectionSent=false;p.castableName=nil
    active={move=p.evade and active and active.move or 0,strafe=p.evade and active and active.strafe or 0,
        run=p.evadeRun or false,attack=false,sneak=pausedSneak}
end
local function prepareChainStep(p)
    local step=p.chain.plan[p.chain.index]
    if step.op=='wait' then
        p.target=p.chain.waitTarget;p.selectionReady=true
        return true
    end
    if not p.selectionSent then
        p.selectionSent=true
        if step.spell then
            local current=A.getSelectedSpell(self)
            if not current or current.id~=step.spell.id or A.getSelectedEnchantedItem(self) then A.setSelectedSpell(self,step.spell);return false end
        end
        if step.item then
            local found=false
            for _,obj in ipairs(A.inventory(self):getAll()) do if obj==step.item then found=true end end
            if not found then finishCombat(p,'item_unavailable');return false end
            if A.getSelectedEnchantedItem(self)~=step.item then A.setSelectedEnchantedItem(self,step.item);return false end
        end
    end
    if step.spell then
        local selected=A.getSelectedSpell(self)
        if not selected or selected.id~=step.spell.id then return false end
    elseif step.item and A.getSelectedEnchantedItem(self)~=step.item then return false end
    local info=combatInfo()
    local selected=step.op=='cast' and info.castable or info.weapon_info
    p.ammoRecord=step.op=='strike' and selected and selected.kind=='ranged' and ammunition() or nil
    p.resources=resources(p.ammoRecord)
    if not selected or step.op=='cast' and not selected.name then finishCombat(p,'nothing_selected');return false end
    p.castableName=selected.name
    if selected.available==false then finishCombat(p,selected.unavailable_reason);return false end
    if step.op=='strike' then
        local old=p.chain.lastWeapon
        if old and (old.kind~=selected.kind or old.name~=selected.name) then finishCombat(p,'weapon_changed');return false end
        p.chain.lastWeapon={kind=selected.kind,name=selected.name}
        p.expectedWeapon={kind=selected.kind,name=selected.name}
    else p.chain.lastWeapon=nil end
    p.spendKind=spendingKind(step.op,selected)
    p.ranged=step.op=='strike' and selected.kind=='ranged'
    local selfOnly=step.op=='cast';local touch=false
    for _,effect in ipairs(selected.effects or {}) do
        if effect.range~='self' then selfOnly=false end
        if effect.range=='touch' then touch=true end
    end
    if not selfOnly and not p.chain.air then
        p.target=p.chain.ref
        if not p.target then finishCombat(p,'target_required');return false end
    end
    p.rangeCheck=step.op=='strike' and selected.kind~='ranged' and 'melee_in_reach' or touch and 'touch_in_reach' or nil
    p.pursuitRangeKind=step.op=='strike' and (selected.kind=='ranged' and 'ranged' or 'melee') or 'touch'
    p.chain.waitTarget=p.target
    p.selectionReady=true
    return true
end
local function finish()
    local p = pending
    if not p.cmd then
        pending=nil
        ready = true
        bus:set('ready', true)
        return
    end
    local result, err = p.result, p.error
    local inputRequired=result and result.reason=='ui_input_required'
    if result and p.finalPose and result.motion then
        -- Physics may finish an already queued movement frame after the pause
        -- request. Report the stable endpoint, not the pre-pause estimate.
        result.motion=Scene.report(p.finalPose)
        if p.pausePose then result.motion.pause_drift_m=Scene.report(p.pausePose).moved_m end
        result.body=bodyState()
        if result.motion.location_changed then
            result.reason='location_changed';result.navigation=nil
        elseif p.finalNavigator then
            local N=require('scripts.astrabridge.navigation')
            result.navigation=N.report(p.finalNavigator)
            if result.reason=='arrived' and not N.reached(p.finalNavigator) then result.reason='settled_outside_goal' end
            if result.reason=='arrived' then
                result.navigation.status='arrived';result.navigation.remaining_m=0;result.navigation.blocked_by=nil
            end
        end
    end
    if result and p.finalAerial then
        if Space.key(self.cell)==p.finalPose.cell then
            Airborne.update(p.finalAerial,A.isOnGround(self),A.isSwimming(self),self.position.z,ownHealth())
        end
        result.aerial=Airborne.report(p.finalAerial,Scene.unitsPerMeter)
        if A.isDead(self) then result.reason='player_down';result.outcome='interrupted' end
    end
    if result and p.finalCombatBase then
        local now=resources(p.finalAmmoRecord)
        result.resources=resourceDelta(p.finalChainBase or p.finalCombatBase,now,p.finalChainBase~=nil)
        if result.steps and #result.steps>0 and not p.combatTail then
            result.steps[#result.steps].resources=resourceDelta(p.finalCombatBase,now,false)
        end
        if A.isDead(self) then result.reason='player_down';result.outcome='interrupted' end
    end
    if result and p.expected then
        result.outcome='activation_sent'
        if p.expected.item and A.inventory(self):countOf(p.expected.item)>p.expected.count then result.outcome='taken'
        elseif I.UI.getMode()==I.UI.MODE.Dialogue then result.outcome='dialogue_opened'
        elseif I.UI.getMode()==I.UI.MODE.Container then result.outcome='container_opened'
        elseif I.UI.getMode()==I.UI.MODE.Book or I.UI.getMode()==I.UI.MODE.Scroll then result.outcome='document_opened'
        elseif Space.key(self.cell)~=p.expected.cell then
            result.outcome='location_changed'
            if result.motion then result.motion.location_changed=true end
        elseif p.expected.door and p.expected.door:isValid() and Scene.resolve(p.expected.ref,true) then
            local door=p.expected.door
            local state=types.Door.getDoorState(door)
            if state~=p.expected.doorState then
                result.outcome=state==types.Door.STATE.Opening and 'door_opening'
                    or state==types.Door.STATE.Closing and 'door_closing'
                    or types.Door.isOpen(door) and 'door_opened' or 'door_closed'
            elseif types.Door.isOpen(door)~=p.expected.doorOpen then
                result.outcome=types.Door.isOpen(door) and 'door_opened' or 'door_closed'
            end
        end
    end
    -- Keep confirmed side effects (e.g. an item taken) while reporting that the
    -- outstanding action yielded to a prompt, including one shown during settle.
    if inputRequired and result.reason~='player_down' then result.reason='ui_input_required' end
    if not err and p.cmd.op == 'observe' then result = observation(p.cmd.args) end
    if not err and p.cmd.op == 'inspect' then result,err = inspect(p.cmd.args) end
    if not err and p.cmd.op=='ui' then result=uiState() end
    if not err and p.cmd.op=='map' and ui._astraMap then
        local args=p.cmd.args
        local action=args.action or 'windowed'
        local map=ui._astraMap(action,args.dx or 0,args.dy or 0,args.factor or 1,args.fit or false)
        if map.error then err=map.error
        else
            map.markers=P.array(map.markers)
            result={map=map,paused=true}
            if action=='close' then I.UI.setMode(nil);result={paused=true,closed=true} end
        end
    end
    pending=nil
    bus:set('response', {session=p.cmd.session,id=p.cmd.id,result=result,error=err})
end

-- Extend normal input values so the engine's usual movement and combat restrictions apply.
local bindings = {
    MoveForward=function(a) return math.max(0,a.move or 0) end,
    MoveBackward=function(a) return math.max(0,-(a.move or 0)) end,
    MoveRight=function(a) return math.max(0,a.strafe or 0) end,
    MoveLeft=function(a) return math.max(0,-(a.strafe or 0)) end,
    Use=function(a) return a.attack or false end,
    Run=function(a) return a.run or false end,
    Sneak=function(a) return a.sneak or false end,
}
for name, getter in pairs(bindings) do
    if not directMovement or name=='Use' then
    input.bindAction(name, async:callback(function(_, previous)
        if manualActive then return previous end
        if active and pending and pending.phase == 'running' and not pending.nativeWait then return getter(active) end
        if name=='Sneak' then return pausedSneak end
        return previous
    end), {})
    end
end

local function dispatch(cmd)
    local op, args = cmd.op, cmd.args
    if op=='stop' and args._runtime_mode then
        clearInput();active=nil;targetLock=nil;routes={};walkingRoute=nil
        manualActive=args._runtime_mode=='manual'
        if directMovement then I.Controls.overrideMovementControls(not manualActive) end
        epoch=epoch+1;bus:set('epoch',epoch);Scene.reset(namespace())
        if Terrain then Terrain.reset(namespace()) end
        invalidate()
        if manualActive then
            pending=nil
            core.sendGlobalEvent('AstraResume',{})
            bus:set('response',{session=cmd.session,id=cmd.id,result={submitted=true,paused=false}})
        else pause(cmd,{submitted=true,paused=true}) end
        return
    end
    if op=='observe' and args._passive and manualActive then
        bus:set('response',{session=cmd.session,id=cmd.id,result=observation(args)})
        return
    end
    if motorOperations[op] and ui._astraUiSnapshot then
        modalOpen=uiState().modal==true
        if modalOpen then pause(cmd,nil,'ui_open');return end
    end
    local guardReason=Guards.check(args._guard,core.getSimulationTime(),A.stats and A.stats.dynamic and A.stats.dynamic.health(self))
    if guardReason then pause(cmd,{paused=true,reason=guardReason,elapsed=0});return end
    if (op=='chain' or op=='strike' or op=='cast') and not windowAllowed('Stats') then
        -- Combat result resource deltas are not available before the tutorial
        -- grants the stat interface. Timed waiting remains possible with act.
        pause(cmd,nil,'view_unavailable');return
    end
    if op == 'observe' or op == 'inspect' or op == 'stop' then
        if op=='stop' then pausedSneak=false end
        pause(cmd, {paused=true})
    elseif op=='target_info' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        pause(cmd,Scene.interactionInfo(args.ref))
    elseif op=='read' then
        if not ui._astraReadDocument then pause(cmd,nil,'native_ui_unavailable');return end
        local ref=args.ref or ''
        local prefix='document_'..namespace()..'_'
        if ref~='' then
            if ref:sub(1,#prefix)~=prefix then pause(cmd,nil,'stale_document_ref');return end
            ref='document_'..ref:sub(#prefix+1)
        end
        local result=ui._astraReadDocument(ref,args.offset or 0,args.limit or 4000)
        if result.reason then pause(cmd,nil,result.reason);return end
        result.ref=prefix..result.ref:sub(10)
        pause(cmd,result)
    elseif op=='resetNPC' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        if not ui._astraResetNPC or types.Actor.isDead(self) then pause(cmd,nil,'action_unavailable');return end
        if not ui._astraResetNPC() then pause(cmd,nil,'action_unavailable');return end
        -- Actor positions changed. Invalidate handles/local plans, preserve travelled atlas.
        epoch=epoch+1;bus:set('epoch',epoch)
        Scene.reset(namespace())
        if Terrain then Terrain.reset(namespace()) end
        routes={};walkingRoute=nil;targetLock=nil;invalidate()
        pause(cmd,{submitted=true,reason='actors_reset',description=args.reason,scope='actors_in_active_cells'})
    elseif op=='survey' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        if Terrain then Terrain.invalidate() end
        pause(cmd,{})
    elseif op=='mark' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        if not Terrain then pause(cmd,nil,'action_unavailable');return end
        pause(cmd,{ref=Terrain.mark(args._atlas_offset,args._atlas_route)})
    elseif op=='pick' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        pause(cmd,Scene.pick(args.x,args.y,args.radius or 0))
    elseif op=='ground' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        pause(cmd,{ground_targets=Scene.groundTargets()})
    elseif op=='ui' then pause(cmd,{})
    elseif op=='unlock' then targetLock=nil;pause(cmd,{})
    elseif op=='map' then
        if not windowAllowed('Map') then pause(cmd,nil,'view_unavailable');return end
        if uiState().modal then pause(cmd,nil,'ui_open');return end
        if I.UI.getMode() and I.UI.getMode()~=I.UI.MODE.Interface then pause(cmd,nil,'ui_open');return end
        local action=args.action or 'windowed'
        if action~='windowed' and not ui._astraMap then pause(cmd,nil,'native_ui_unavailable');return end
        if action=='windowed' or action=='local' or action=='world' then
            I.UI.setMode(I.UI.MODE.Interface,{windows={'Map'}})
        elseif I.UI.getMode()~=I.UI.MODE.Interface then pause(cmd,nil,'map_not_open');return end
        pause(cmd,{})
    elseif op=='ui_scroll' then
        if not ui._astraUiScroll then pause(cmd,nil,'native_ui_unavailable');return end
        local steps=P.number(args.steps,-10,10)
        if steps~=math.floor(steps) then pause(cmd,nil,'invalid_arguments');return end
        if not ui._astraUiScroll(steps) then pause(cmd,nil,'ui_scroll_unavailable');return end
        pause(cmd,{submitted=true})
    elseif op=='choose' or op=='edit' or op=='adjust' or op=='ui_hover' then
        walkingRoute=nil
        if not ui._astraUiChoose then pause(cmd,nil,'native_ui_unavailable');return end
        local prefix='ui_'..namespace()..'_'
        if args.ref:sub(1,#prefix)~=prefix then pause(cmd,nil,'stale_ui_ref');return end
        local chosenText,chosenRole
        for _,entry in ipairs(uiState().elements) do
            if entry.ref==args.ref and op~='ui_hover' and not entry.enabled then pause(cmd,nil,'ui_control_disabled');return end
            if entry.ref==args.ref and op=='ui_hover' and entry.screen_visible==false then pause(cmd,nil,'ui_element_offscreen');return end
            if entry.ref==args.ref and op=='adjust' and (entry.role~='slider' or args.position>entry.slider_max) then pause(cmd,nil,'invalid_arguments');return end
            if entry.ref==args.ref then chosenText,chosenRole=entry.text,entry.role end
        end
        local native='ui_'..args.ref:sub(#prefix+1)
        local accepted
        if op=='ui_hover' then
            if not ui._astraUiHover then pause(cmd,nil,'native_ui_unavailable');return end
            accepted=ui._astraUiHover(native)
        elseif op=='adjust' then
            if not ui._astraUiAdjust then pause(cmd,nil,'native_ui_unavailable');return end
            accepted=ui._astraUiAdjust(native,args.position)
        elseif op=='edit' then
            if not ui._astraUiEdit then pause(cmd,nil,'native_ui_unavailable');return end
            accepted=ui._astraUiEdit(native,args.text)
        else accepted=ui._astraUiChoose(native) end
        if not accepted then pause(cmd,nil,'stale_ui_ref');return end
        pause(cmd,{submitted=true,chosen_text=chosenText,chosen_role=chosenRole})
    elseif op=='fov' then
        desiredFov=P.number(args.degrees,70,115,100)
        bus:set('horizontal_fov',desiredFov)
        Scene.fov(desiredFov)
        pause(cmd,{})
    elseif op=='chain' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        if not controlsAllowed() then pause(cmd,nil,'action_unavailable');return end
        if not ui._astraCombatInfo then pause(cmd,nil,'native_ui_unavailable');return end
        assert(type(args.actions)=='table' and #args.actions>=1)
        local plan={}
        for _,step in ipairs(args.actions) do
            assert(step.op=='strike' or step.op=='cast' or step.op=='wait')
            local switch=step.op=='cast' and Player.CONTROL_SWITCH.Magic or Player.CONTROL_SWITCH.Fighting
            if step.op~='wait' and not Player.getControlSwitch(self,switch) then pause(cmd,nil,'action_unavailable');return end
            local entry={op=step.op,charge=P.number(step.charge,.1,1.5,.8),seconds=step.op=='wait' and P.number(step.seconds,.02,math.huge,.5) or nil}
            if step.spell then
                for _,spell in pairs(A.spells(self)) do
                    if spell.name==step.spell and (spell.type==core.magic.SPELL_TYPE.Spell or spell.type==core.magic.SPELL_TYPE.Power) then
                        if entry.spell then pause(cmd,nil,'selection_ambiguous');return end
                        entry.spell=spell
                    end
                end
                if not entry.spell then pause(cmd,nil,'selection_unavailable');return end
            elseif step.item then
                for _,obj in ipairs(A.inventory(self):getAll()) do
                    local record=obj.type.record(obj)
                    if record.name==step.item and record.enchant then
                        local enchantment=core.magic.enchantments.records[record.enchant]
                        if enchantment.type==core.magic.ENCHANTMENT_TYPE.CastOnUse or enchantment.type==core.magic.ENCHANTMENT_TYPE.CastOnce then
                            if entry.item then pause(cmd,nil,'selection_ambiguous');return end
                            entry.item=obj
                        end
                    end
                end
                if not entry.item then pause(cmd,nil,'selection_unavailable');return end
            end
            plan[#plan+1]=entry
        end
        local target=args.ref or (not args.air and targetLock and targetLock.status~='down' and targetLock.ref)
        if args.pursue then
            if not directMovement or not Terrain or not ui._astraTargetReach then pause(cmd,nil,'action_unavailable');return end
            if not target then pause(cmd,nil,'target_required');return end
            if args.movement or args.air then pause(cmd,nil,'invalid_arguments');return end
            local g=Scene.track(target)
            if not g or not A.objectIsInstance(g.obj) or A.isDead(g.obj) then pause(cmd,nil,'target_not_visible');return end
        end
        if args.movement then
            if not Terrain then pause(cmd,nil,'action_unavailable');return end
            local m=args.movement
            assert(m.direction=='forward' or m.direction=='back' or m.direction=='left' or m.direction=='right')
            if m.face_target==true and not target then pause(cmd,nil,'target_required');return end
            if m.face_target==false and target then pause(cmd,nil,'movement_conflicts_with_target');return end
        end
        if args.air and targetLock then pause(cmd,nil,'target_locked_unlock_first');return end
        if args.ref then
            if targetLock and targetLock.ref~=target then pause(cmd,nil,'target_locked_unlock_first');return end
            local g=Scene.resolve(target,true)
            if not g or not A.objectIsInstance(g.obj) then pause(cmd,nil,'target_not_visible');return end
            targetLock={ref=target,status=A.isDead(g.obj) and 'down' or 'locked',cell=Space.key(self.cell)}
        end
        local p={cmd=cmd,phase='resuming',start=Scene.pose(),elapsed=0,deadline=core.getRealTime()+P.actionTimeout(op,args,45),
            chain={plan=plan,ref=target,air=args.air,limit=P.number(args.max_seconds,.5,math.huge,12),elapsed=0,
                stopHealth=P.number(args.stop_health_pct,0,100,0),results=P.array(),completed=0,initial=resources()}}
        if args.movement then
            local m=args.movement
            p.evade=Evasion.new(m.direction,P.number(m.meters,.25,math.huge,2),p.chain.limit)
            p.evadePosition=self.position;p.evadeRun=m.run or false
            p.evadeFaceTarget=m.face_target~=false and target~=nil
            p.evadeTarget=target
            routes={};walkingRoute=nil
        end
        if args.pursue then
            p.pursuit=Pursuit.new();p.pursuit.position=self.position
            routes={};walkingRoute=nil
        end
        pending=p;beginChainStep(p,1);invalidate()
        core.sendGlobalEvent('AstraResume',{id=cmd.id})
    elseif op=='strike' or op=='cast' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        if not controlsAllowed() then pause(cmd,nil,'action_unavailable');return end
        local switch=op=='cast' and Player.CONTROL_SWITCH.Magic or Player.CONTROL_SWITCH.Fighting
        if not Player.getControlSwitch(self,switch) then pause(cmd,nil,'action_unavailable');return end
        if not ui._astraCombatInfo then pause(cmd,nil,'native_ui_unavailable');return end
        local info=combatInfo()
        local selected=op=='cast' and info.castable or info.weapon_info
        if not selected or op=='cast' and not selected.name then pause(cmd,nil,'nothing_selected');return end
        if selected.available==false then pause(cmd,{paused=true,attempted=false,outcome='not_attempted',reason=selected.unavailable_reason});return end
        local selfOnly=op=='cast'
        local touch=false
        for _,e in ipairs(selected.effects or {}) do
            if e.range~='self' then selfOnly=false end
            if e.range=='touch' then touch=true end
        end
        local target=args.ref or (not args.air and not selfOnly and targetLock and targetLock.ref)
        if args.air and targetLock then pause(cmd,nil,'target_locked_unlock_first');return end
        if not selfOnly and not args.air and not target then pause(cmd,nil,'target_required');return end
        if target and targetLock and targetLock.ref~=target then pause(cmd,nil,'target_locked_unlock_first');return end
        if target then
            local g=Scene.resolve(target,true)
            if not g then pause(cmd,nil,'target_not_visible');return end
            if not A.objectIsInstance(g.obj) or A.isDead(g.obj) then pause(cmd,nil,'invalid_lock_target');return end
            targetLock={ref=target,status='locked',cell=Space.key(self.cell)}
        end
        local charge=P.number(args.charge,.1,1.5,.8)
        active={move=0,strafe=0,attack=false,sneak=pausedSneak}
        local ammoRecord=op=='strike' and selected.kind=='ranged' and ammunition() or nil
        pending={cmd=cmd,phase='resuming',start=Scene.pose(),elapsed=0,deadline=core.getRealTime()+P.actionTimeout(op,args,45),
            combat=Combat.new(op,charge),resources=resources(ammoRecord),ammoRecord=ammoRecord,spendKind=spendingKind(op,selected),firstFrame=lastFrame,target=target,
            rangeCheck=op=='strike' and selected.kind~='ranged' and 'melee_in_reach' or touch and 'touch_in_reach' or nil}
        pending.castableName=selected.name
        pending.ranged=op=='strike' and selected.kind=='ranged'
        if op=='strike' then pending.expectedWeapon={kind=selected.kind,name=selected.name} end
        invalidate()
        core.sendGlobalEvent('AstraResume',{id=cmd.id})
    elseif op=='evade' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        if not Terrain or not controlsAllowed() or not Player.getControlSwitch(self,Player.CONTROL_SWITCH.Looking) then pause(cmd,nil,'action_unavailable');return end
        local target=args.ref or targetLock and targetLock.ref
        if not target then pause(cmd,nil,'target_required');return end
        if targetLock and targetLock.ref~=target then pause(cmd,nil,'target_locked_unlock_first');return end
        local g=targetLock and Scene.track(target) or Scene.resolve(target,true)
        if not g then pause(cmd,nil,'target_not_visible');return end
        if not A.objectIsInstance(g.obj) then pause(cmd,nil,'invalid_lock_target');return end
        if A.isDead(g.obj) then pause(cmd,{paused=true,reason='target_down'});return end
        assert(args.direction=='back' or args.direction=='left' or args.direction=='right')
        local meters=P.number(args.meters,.25,math.huge,2)
        local seconds=P.number(args.seconds,.2,math.huge,4)
        targetLock={ref=target,status='locked',cell=Space.key(self.cell)}
        routes={};walkingRoute=nil
        active={move=0,strafe=0,run=args.run or false,sneak=pausedSneak}
        pending={cmd=cmd,phase='resuming',start=Scene.pose(),elapsed=0,deadline=core.getRealTime()+P.actionTimeout(op,args,30),
            kind='evade',evade=Evasion.new(args.direction,meters,seconds),evadePosition=self.position,
            evadeRun=args.run or false,evadeFaceTarget=true,evadeTarget=target}
        invalidate();core.sendGlobalEvent('AstraResume',{id=cmd.id})
    elseif op=='fly' or op=='swim' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        if not controlsAllowed() or not Player.getControlSwitch(self,Player.CONTROL_SWITCH.Looking) then pause(cmd,nil,'action_unavailable');return end
        if op=='fly' and not Mobility.has('Levitate') then pause(cmd,nil,'levitation_required');return end
        if op=='swim' and not A.isSwimming(self) then pause(cmd,nil,'swimming_required');return end
        if targetLock and targetLock.status~='down' then pause(cmd,nil,'target_locked_unlock_first');return end
        local f=P.number(args.forward_m,-math.huge,math.huge,0)
        local s=P.number(args.sideways_m,-math.huge,math.huge,0)
        local z=P.number(args.vertical_m,-math.huge,math.huge,0)
        assert(args.ref or f*f+s*s+z*z>.01)
        local yaw=camera.getYaw()
        local delta=util.vector3(f*math.sin(yaw)+s*math.cos(yaw),f*math.cos(yaw)-s*math.sin(yaw),z)*Scene.unitsPerMeter
        local goal={groundPoint=self.position+delta,freeDestination=true}
        if args.ref then
            local point=Terrain and Terrain.resolve(args.ref) or Scene.resolveGround(args.ref)
            if point then goal={groundPoint=point,freeDestination=true}
            else
                goal=Scene.resolve(args.ref)
                if not goal then pause(cmd,nil,'target_not_visible');return end
                goal.freeDestination=true
            end
        end
        local N=require('scripts.astrabridge.navigation')
        local nav=N.new(goal);N.begin(nav);nav.inputDelayFrames=directMovement and 0 or 2
        active={move=0,strafe=0,run=false,sneak=pausedSneak}
        walkingRoute=nil
        pending={cmd=cmd,phase='resuming',start=Scene.pose(),elapsed=0,deadline=core.getRealTime()+P.actionTimeout(op,args,60),
            kind='walk',navigator=nav,requiredMode=op=='fly' and 'air' or 'swim',
            maxSeconds=P.number(args.seconds,.2,math.huge,op=='swim' and 30 or 10),lastHealth=not args.under_fire and ownHealth() or nil}
        invalidate();core.sendGlobalEvent('AstraResume',{id=cmd.id})
    elseif op=='walk' or op=='go' then
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        if not controlsAllowed() then pause(cmd,nil,'action_unavailable');return end
        if targetLock and targetLock.status~='down' then pause(cmd,nil,'target_locked_unlock_first');return end
        local N=require('scripts.astrabridge.navigation')
        if op=='go' and (not walkingRoute or walkingRoute.ref~=args.ref) then
            local point=Terrain and Terrain.resolve(args.ref) or Scene.resolveGround(args.ref)
            if not point then pause(cmd,nil,'stale_ref');return end
            walkingRoute={ref=args.ref,nav=N.new({groundPoint=point,recordedPath=Terrain and Terrain.route(args.ref)})}
        elseif args.ref and args.ref:sub(1,7)=='ground_' and (not walkingRoute or walkingRoute.ref~=args.ref) then
            local point=Scene.resolveGround(args.ref)
            if not point then pause(cmd,nil,'stale_ref');return end
            walkingRoute={ref=args.ref,nav=N.new({groundPoint=point})}
        elseif args.ref then
            if not walkingRoute or walkingRoute.ref~=args.ref or walkingRoute.nav.cell~=Space.key(self.cell)
                or (walkingRoute.nav.goal-self.position):length()>7000 then pause(cmd,nil,'stale_ref');return end
        else
            local point=Scene.groundPoint(args.x,args.y)
            if not point then pause(cmd,nil,'point_not_ground');return end
            serial=serial+1
            walkingRoute={ref='walk_'..namespace()..'_'..serial,nav=N.new({groundPoint=point})}
        end
        active={move=0,strafe=0,run=args.run or false,sneak=pausedSneak}
        N.begin(walkingRoute.nav)
        walkingRoute.nav.inputDelayFrames=directMovement and 0 or 2
        local goalDelta=walkingRoute.nav.goal-self.position
        walkingRoute.nav.arrivalTolerance=op=='go' and args.ref:sub(1,8)=='passage_'
            and math.min(84,math.max(25,math.sqrt(goalDelta.x^2+goalDelta.y^2)*.25)) or 25
        pending={cmd=cmd,phase='resuming',start=Scene.pose(),elapsed=0,deadline=core.getRealTime()+P.actionTimeout(op,args,45),
            kind='walk',navigator=walkingRoute.nav,walkRef=walkingRoute.ref,
            lastHealth=not args.under_fire and ownHealth() or nil,progressPosition=self.position,progressTime=0,maxSeconds=P.number(args.seconds,.5,math.huge,op=='go' and 12 or 8)}
        invalidate();core.sendGlobalEvent('AstraResume',{id=cmd.id})
    elseif op=='focus' or op=='approach' or op=='interact' or op=='move_local' or op=='track' or op=='lock' then
        local interaction=op=='interact'
        if interaction then op=args.approach and 'approach' or 'focus' end
        if op=='move_local' and Mobility.has('Levitate') then pause(cmd,nil,'flight_requires_fly');return end
        if op=='approach' or op=='move_local' then walkingRoute=nil end
        if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
        if not controlsAllowed() then pause(cmd,nil,'action_unavailable');return end
        local start=Scene.pose()
        local g
        if op~='move_local' then
            g=Scene.resolve(args.ref,true)
            local cached=op=='approach' and routes[args.ref]
            if not g and cached and not cached.movingTarget and cached.cell==Space.key(self.cell)
                and core.getSimulationTime()-(cached.lastUse or 0)<60 then g=cached.lastGoal end
            if not g then pause(cmd,nil,'target_not_visible');return end
        end
        if op=='approach' and args.reach and args.reach~='activate' then
            if not ui._astraTargetReach then pause(cmd,nil,'native_ui_unavailable');return end
            if not A.objectIsInstance(g.obj) then pause(cmd,nil,'action_unavailable');return end
        end
        if op=='lock' then
            if not types.Actor.objectIsInstance(g.obj) or A.isDead(g.obj) then pause(cmd,nil,'invalid_lock_target');return end
            targetLock={ref=args.ref,status='locked',cell=Space.key(self.cell)}
        elseif targetLock and targetLock.status=='locked' and args.ref and args.ref~=targetLock.ref then
            pause(cmd,nil,'target_locked_unlock_first');return
        end
        active={move=0,strafe=0,sneak=pausedSneak,run=args.run or false}
        pending={cmd=cmd,phase='resuming',start=start,elapsed=0,seconds=P.actionSeconds(op,args),deadline=core.getRealTime()+P.actionTimeout(op,args,45),
            kind=op=='lock' and 'focus' or op,target=args.ref,progressTime=0,progressPosition=self.position,interact=interaction,
            reachKind=args.reach,waitReady=args.wait_ready}
        if op=='track' then
            pending.seconds=P.number(args.seconds,.1,math.huge,1)
            pending.deadline=core.getRealTime()+P.actionTimeout(op,args,45)
            assert(args.attack==nil or type(args.attack)=='boolean')
            pending.attack=args.attack or false
        end
        if op=='move_local' then
            local forward=P.number(args.forward_m,-math.huge,math.huge,0)*Scene.unitsPerMeter
            local side=P.number(args.sideways_m,-math.huge,math.huge,0)*Scene.unitsPerMeter
            pending.destination=self.position+util.vector3(forward*math.sin(start.yaw)+side*math.cos(start.yaw),
                forward*math.cos(start.yaw)-side*math.sin(start.yaw),0)
        end
        if (op=='move_local' or op=='approach' and (not args.reach or args.reach=='activate')) and not args.under_fire then pending.lastHealth=ownHealth() end
        if op=='approach' then
            local n=routes[args.ref]
            if not n or n.cell~=Space.key(self.cell) then n=require('scripts.astrabridge.navigation').new(g) end
            local N=require('scripts.astrabridge.navigation');if N.begin then N.begin(n) end
            n.inputDelayFrames=directMovement and 0 or 2
            n.lastUse=core.getSimulationTime();routes[args.ref]=n;pending.navigator=n
        elseif op=='move_local' then routes={} end
        invalidate()
        core.sendGlobalEvent('AstraResume',{id=cmd.id})
    elseif op == 'act' or op=='look' or op=='wait_until' or op=='jump' or op=='air_move' then
        local aerialKind
        if op=='jump' or op=='air_move' then
            if I.UI.getMode() then pause(cmd,nil,'ui_open');return end
            if not controlsAllowed() or not A.canMove(self) or A.isDead(self) then pause(cmd,nil,'action_unavailable');return end
            if Mobility.has('Levitate') then pause(cmd,nil,'flight_requires_fly');return end
            if A.isSwimming(self) then pause(cmd,nil,'swimming_requires_swim');return end
            if op=='jump' and not A.isOnGround(self) then pause(cmd,nil,'jump_requires_ground');return end
            if op=='air_move' and A.isOnGround(self) then pause(cmd,nil,'airborne_required');return end
            -- Keep relative directions stable throughout the action.
            if targetLock and targetLock.status~='down' then pause(cmd,nil,'locked_camera');return end
            local direction=Airborne.directions[args.direction or 'none'];assert(direction)
            aerialKind=op
            args={move=direction[1],strafe=direction[2],run=args.run or false,
                trigger=op=='jump' and 'Jump' or nil,seconds=P.actionSeconds(op,args)}
        elseif op=='act' and args.trigger=='Jump' then aerialKind='act' end
        local waitCondition
        if op=='wait_until' then
            waitCondition=args
            if args.condition=='landed' then aerialKind='landed' end
            args={seconds=P.actionSeconds(op,args)}
        end
        if op=='look' then
            local heading=P.number(args.heading_deg,0,360,nil)
            local pitch=P.number(args.pitch_deg,-80,80,nil)
            args={seconds=.02,sneak=pausedSneak,yaw=heading and math.deg(Scene.angle(math.rad(heading)-camera.getYaw())) or nil,
                pitch=pitch and pitch-math.deg(camera.getPitch()) or nil}
        end
        if I.UI.getMode() then pause(cmd,nil,'ui_open'); return end
        if targetLock and targetLock.status=='down' and args.attack then pause(cmd,nil,'invalid_lock_target');return end
        if targetLock and targetLock.status~='down' then
            if not lockedTarget() then
                if targetLock.status=='down' then pause(cmd,{paused=true,reason='target_down',elapsed=0})
                else pause(cmd,nil,'target_not_visible') end
                return
            end
            if (args.yaw or 0)~=0 or (args.pitch or 0)~=0 then pause(cmd,nil,'locked_camera');return end
            if args.target and args.target~=targetLock.ref then pause(cmd,nil,'target_locked_unlock_first');return end
        end
        local expected
        if args.target then
            local g=Scene.resolve(args.target)
            if not g then pause(cmd,nil,'target_not_visible');return end
            if not Scene.reach(g) then pause(cmd,nil,'out_of_reach');return end
            if not Scene.crosshair(g) then pause(cmd,nil,'target_not_aimed');return end
            expected={cell=Space.key(self.cell)}
            if types.Item.objectIsInstance(g.obj) then
                expected.item=g.obj.recordId;expected.count=A.inventory(self):countOf(expected.item)
            end
        end
        local seconds = P.number(args.seconds,0.02,math.huge,0.25)
        P.number(args.move,-1,1,0); P.number(args.strafe,-1,1,0)
        P.number(args.yaw,-180,180,0); P.number(args.pitch,op=='look' and -180 or -90,op=='look' and 180 or 90,0)
        for _, k in ipairs({'attack','run','sneak'}) do assert(args[k] == nil or type(args[k]) == 'boolean') end
        if args.trigger then assert(allowedTriggers[args.trigger]) end
        if directMovement and args.trigger=='Jump' and not Player.getControlSwitch(self,Player.CONTROL_SWITCH.Jumping) then pause(cmd,nil,'action_unavailable');return end
        if ((args.yaw or 0)~=0 or (args.pitch or 0)~=0)
            and not Player.getControlSwitch(self,Player.CONTROL_SWITCH.Looking) then pause(cmd,nil,'action_unavailable');return end
        if (args.move or 0)~=0 or (args.strafe or 0)~=0 then routes={};walkingRoute=nil end
        pausedSneak=args.sneak or false
        invalidate()
        active = args
        local start=Scene.pose()
        pending = {cmd=cmd,phase='resuming',seconds=seconds,elapsed=0,deadline=core.getRealTime()+P.actionTimeout(op,args,30),start=start,
            turnYaw=args.yaw~=nil,turnPitch=args.pitch~=nil,
            yaw=start.yaw+math.rad(args.yaw or 0),pitch=args.pitch and math.max(-1.45,math.min(1.45,start.pitch+math.rad(args.pitch))) or start.pitch,expected=expected,
            requestedAttack=args.attack or false,waitCondition=waitCondition}
        if aerialKind then pending.aerial=Airborne.begin(aerialKind,A.isOnGround(self),self.position.z,ownHealth()) end
        pending.requestedMove=args.move or 0;pending.requestedStrafe=args.strafe or 0
        core.sendGlobalEvent('AstraResume', {id=cmd.id})
    elseif op == 'trigger' then
        if args.name=='Rest' then
            if not ui._astraRest then pause(cmd,nil,'native_ui_unavailable');return end
            local opened=ui._astraRest()
            pause(cmd,{paused=true,submitted=opened,reason=opened and 'ui_opened' or 'rest_unavailable'});return
        end
        assert(allowedTriggers[args.name])
        -- Activation/jump need simulation and therefore belong in act.
        if args.name == 'Activate' or args.name == 'Jump' then pause(cmd,nil,'use_act'); return end
        input.activateTrigger(args.name)
        invalidate()
        pause(cmd,{paused=true})
    elseif op == 'use_item' or op == 'select_spell' or op=='select_enchanted' then
        local r = refs[args.ref]
        if not r then pause(cmd,nil,'stale_ref'); return end
        if not controlsAllowed() then pause(cmd,nil,'action_unavailable'); return end
        if (op == 'use_item' or op=='select_enchanted') and r.kind == 'item' and windowAllowed('Inventory') then
            local found = false
            for _, obj in ipairs(A.inventory(self):getAll()) do if obj == r.value then found = true end end
            if not found then pause(cmd,nil,'stale_ref'); return end
            local mode = I.UI.getMode()
            if mode and mode ~= I.UI.MODE.Interface then pause(cmd,nil,'action_unavailable'); return end
            -- Inventory use is allowed while paused, just like dragging onto the paper doll.
            if op=='select_enchanted' then
                if not windowAllowed('Magic') then pause(cmd,nil,'view_unavailable');return end
                local id=r.value.type.record(r.value).enchant
                local enchantment=id and core.magic.enchantments.records[id]
                if not enchantment or (enchantment.type~=core.magic.ENCHANTMENT_TYPE.CastOnUse
                    and enchantment.type~=core.magic.ENCHANTMENT_TYPE.CastOnce) then
                    pause(cmd,nil,'action_unavailable');return
                end
                A.setSelectedEnchantedItem(self,r.value)
            else core.sendGlobalEvent('UseItem',{object=r.value,actor=self.object}) end
        elseif op == 'select_spell' and r.kind == 'spell' and windowAllowed('Magic') then
            if not A.spells(self)[r.value.id] then pause(cmd,nil,'stale_ref'); return end
            A.setSelectedSpell(self,r.value)
        else pause(cmd,nil,'action_unavailable'); return end
        invalidate()
        pause(cmd,{submitted=true,paused=true})
    else pause(cmd,nil,'unknown_operation') end
end

local function stopMovement()
    active.move=0;active.strafe=0
    self.controls.movement=0;self.controls.sideMovement=0
end

local function adjustViewpoint(p)
    if not p.interact or p.cmd.args.adjust_viewpoint==false or not Terrain or not A.isOnGround(self) then return false end
    p.viewpointAttempts=(p.viewpointAttempts or 0)+1
    if p.viewpointAttempts>2 then return false end
    local side=p.viewpointAttempts==1 and -math.pi/2 or math.pi/2
    local probe=Terrain.probe(camera.getYaw()+side,.4)
    if probe.obstacle or probe.distance<24 or math.abs(probe.vertical)>15 or not Terrain.walkLine(self.position,probe.point) then return false end
    p.viewpointGoal=probe.point;p.viewpointStart=p.elapsed
    stopMovement();return true
end

local function driveEvasion(p,g,dt)
    if not p.evade then stopMovement();return end
    local delta=self.position-p.evadePosition
    local unit=p.evadeUnit or p.evadeLastUnit
    local moved=unit and math.max(0,delta.x*unit.x+delta.y*unit.y)/Scene.unitsPerMeter or 0
    p.evadePosition=self.position;p.evadeUnit=nil
    -- Continue looking at the selected enemy even after the movement lane ends
    -- while a healing/casting lane is still running.
    if p.evadeFaceTarget and g and not A.isDead(g.obj) then
        targetLock.status='locked'
        local yaw,pitch=Scene.lookAngles(g)
        self.controls.yawChange=Turning.delta(camera.getYaw(),yaw,dt)
        self.controls.pitchChange=Turning.delta(camera.getPitch(),pitch,dt)
    elseif p.evadeFaceTarget then
        targetLock.status=g and 'down' or 'lost'
    end
    if p.evade.reason then
        p.evade.travelled=p.evade.travelled+moved
        stopMovement();return
    end
    p.evade.elapsed=p.chain and p.chain.elapsed-dt or p.elapsed
    if p.evadeFaceTarget and (not g or A.isDead(g.obj)) then
        p.evade.elapsed=p.evade.elapsed+dt;p.evade.travelled=p.evade.travelled+moved
        stopMovement()
        p.evadeMissing=(p.evadeMissing or 0)+dt
        if g then p.evade.reason='target_down';targetLock.status='down'
        elseif p.evadeMissing>=.35 then p.evade.reason='target_lost';targetLock.status='lost' end
        return
    end
    p.evadeMissing=0
    active.run=p.evadeRun
    local speed=(active.run and A.getRunSpeed(self) or A.getWalkSpeed(self))/Scene.unitsPerMeter
    local frame=speed*math.max(directMovement and .2 or .02,dt)
    local motionYaw=camera.getYaw()+(directMovement and (self.controls.yawChange or 0) or 0)
    local x,y=Evasion.unit(p.evade.direction,motionYaw)
    local probe
    if A.isOnGround(self) and not A.isSwimming(self) then
        local ok,value=pcall(Terrain.probe,math.atan2(x,y),math.min(6,math.max(.75,frame*2+.5)))
        if ok then probe=value end
    end
    local c=Evasion.step(p.evade,{moved_m=moved,dead=A.isDead(self),can_move=A.canMove(self),
        on_ground=A.isOnGround(self),swimming=A.isSwimming(self),aligned=not p.evadeFaceTarget or Scene.combatAligned(g),
        frame_distance_m=frame,clear_m=probe and probe.distance/Scene.unitsPerMeter,
        input_delay_frames=directMovement and 0 or 2,
        obstacle=probe and probe.obstacle or 'probe_unavailable'},dt)
    active.move,active.strafe=c.move,c.strafe
    if c.move~=0 or c.strafe~=0 then
        p.evadeUnit=util.vector3(x,y,0);p.evadeLastUnit=p.evadeUnit
    else stopMovement() end
end

local function drivePursuit(p,g,rangeKind,dt)
    local s=p.pursuit
    s.elapsed=p.chain.elapsed-dt
    local moved=(self.position-s.position):length()/Scene.unitsPerMeter
    s.position=self.position
    local reach=g and ui._astraTargetReach(g.obj) or {}
    local key=rangeKind or s.rangeKind or 'touch'
    s.rangeKind=key
    local inRange=key=='ranged' or reach[key..'_in_reach'] or false
    local move=Pursuit.step(s,{moved_m=moved,target_lost=not g,target_down=g and A.isDead(g.obj),
        can_move=A.canMove(self),swimming=A.isSwimming(self),ranged=key=='ranged',
        in_reach=inRange,margin=reach[key..'_margin_m']},dt)
    if not move then stopMovement();return end
    local N=require('scripts.astrabridge.navigation')
    if not s.nav then
        s.nav=N.new(g);N.begin(s.nav)
        s.nav.inputDelayFrames=0;s.nav.replanInterval=.3
        s.progressPosition=self.position;s.progressTime=s.elapsed
    end
    local point=N.step(s.nav,g,dt)
    if s.nav.status=='waiting' then
        s.status='waiting';s.progressTime=s.elapsed;stopMovement();return
    end
    if not point then
        if inRange then s.holding=true;s.status='holding_range';stopMovement();return end
        if N.recover(s.nav,camera.getYaw()) then s.progressTime=s.elapsed;stopMovement();return end
        s.reason=s.nav.path and 'path_end_out_of_reach' or 'no_path';stopMovement();return
    end
    local clearance=N.clearance(s.nav,point)
    if clearance==0 and inRange then
        s.holding=true;s.status='holding_range';s.progressTime=s.elapsed;stopMovement();return
    end
    local d=point-self.position
    local yaw=math.atan2(d.x,d.y)
    local facing=camera.getYaw()+(self.controls.yawChange or 0)
    local angle=Scene.angle(yaw-facing)
    local amount=N.moveFraction(point,dt,true,s.nav)*clearance
    active.run=true;active.move=math.cos(angle)*amount;active.strafe=math.sin(angle)*amount
    if amount==0 then stopMovement() end
    if (self.position-s.progressPosition):length()>3 then s.progressTime=s.elapsed;s.progressPosition=self.position end
    if s.elapsed-s.progressTime>1.1 then
        if N.recover(s.nav,yaw) then s.progressTime=s.elapsed;s.progressPosition=self.position
        else s.reason='blocked';stopMovement() end
    end
end

local function shotAngles(p,g,b,dt)
    local yaw,pitch=Scene.lookAngles(g)
    if not p.ranged or not ui._astraProjectileParameters then return yaw,pitch,Scene.combatAligned(g) end
    local parameters=ui._astraProjectileParameters()
    p.aimAssistance='direct';p.aimNote=nil
    if not parameters.supported then return yaw,pitch,Scene.combatAligned(g) end
    local state=p.ballistic or {};p.ballistic=state
    local using=self.controls.use~=nil and self.controls.use~=self.ATTACK_TYPE.NoAttack
    -- The stock input's release edge is also when CharacterController latches
    -- this animation's windup strength. Do not read later follow-through as 100%.
    if state.using and not using and not state.strength then state.strength=parameters.strength end
    state.using=using
    local velocity=Ballistics.sample(state,g.center,dt)
    local speed=parameters.speed_min+(parameters.speed_max-parameters.speed_min)*(state.strength or 1)
    local delta=(g.point or g.center)-parameters.origin
    local launch,flight=Ballistics.solve(delta,velocity,speed,parameters.gravity,dt)
    if not launch then p.aimNote='ballistic_unreachable';return yaw,pitch,false,p.aimNote end
    p.aimAssistance='ballistic';p.aimFlight=flight
    yaw=math.atan2(launch.x,launch.y)
    pitch=-math.atan2(launch.z,math.sqrt(launch.x^2+launch.y^2))
    local aligned=math.abs(Scene.angle(yaw-camera.getYaw()))<math.rad(2) and math.abs(pitch-camera.getPitch())<math.rad(2)
    if p.combat.phase=='prepare' and b.stance=='weapon' and not b.animation_busy then
        local from=parameters.origin
        for i=1,8 do
            local time=flight*i/8
            local point=parameters.origin+util.vector3(launch.x*time,launch.y*time,
                launch.z*time-parameters.gravity*time*(time+dt)*.5)
            local hit=require('openmw.nearby').castRay(from,point,{ignore=self.object})
            if hit.hit then
                if hit.hitObject~=g.obj then p.aimNote='shot_path_blocked';return yaw,pitch,false,p.aimNote end
                break
            end
            from=point
        end
    end
    return yaw,pitch,aligned
end
local function combatFrame(p,dt)
    if I.UI.getMode() then finishCombat(p,'ui_open');return end
    if A.isDead(self) then finishCombat(p,'player_down');return end
    if p.chain and p.chain.stopHealth>0 then
        local h=A.stats.dynamic.health(self)
        local maximum=math.max(1,h.base+(h.modifier or 0))
        if h.current/maximum*100<=p.chain.stopHealth then finishCombat(p,'health_low');return end
    end
    if core.getRealTime()>p.deadline then finishCombat(p,'wall_time_limit');return end
    if core.isWorldPaused() then
        p.pausedFrames=(p.pausedFrames or 0)+1
        if p.pausedFrames>=3 then finishCombat(p,'game_paused') end
        return
    end
    p.pausedFrames=0
    if p.chain then
        p.chain.elapsed=p.chain.elapsed+dt
        if p.chain.elapsed>=p.chain.limit then finishCombat(p,'chain_time_limit');return end
        if p.evade then
            local g=p.evadeFaceTarget and Scene.track(p.evadeTarget) or nil
            driveEvasion(p,g,dt)
        end
        if p.finishedCombatResult then
            if p.evade.reason then finishCombat(p) end
            return
        end
        if not p.selectionReady and not prepareChainStep(p) then return end
    end
    local b=bodyState()
    local context={stance=b.stance,busy=b.animation_busy,recovering=b.recovering,can_move=b.can_move,dead=A.isDead(self)}
    context.wait_for_range=p.evade and p.evadeFaceTarget and p.evade.direction=='forward' and not p.evade.reason or false
    if p.combat.kind=='cast' then context.animation_active=b.casting else context.animation_active=b.animation_busy end
    if p.target then
        local g=Scene.track(p.target)
        if not g then
            p.ballistic=nil
            targetLock.status='lost'
            stopMovement()
            p.missingTarget=(p.missingTarget or 0)+dt
            if (p.combat.phase=='prepare' or p.combat.phase=='wait') and p.missingTarget<.35 then
                active.attack=false;p.combat.elapsed=p.combat.elapsed+dt;p.elapsed=p.combat.elapsed
                return
            end
            context.target_lost=true
        else
            p.missingTarget=0
            context.target_down=A.isDead(g.obj)
            targetLock.status=context.target_down and 'down' or 'locked'
            if not context.target_down then
                local yaw,pitch,aligned,unavailable=shotAngles(p,g,b,dt)
                self.controls.yawChange=Turning.delta(camera.getYaw(),yaw,dt)
                self.controls.pitchChange=Turning.delta(camera.getPitch(),pitch,dt)
                context.aligned=aligned
                context.unavailable_reason=unavailable
                if p.rangeCheck then context.in_reach=ui._astraTargetReach(g.obj)[p.rangeCheck] end
            end
        end
    elseif targetLock and not p.evadeFaceTarget and targetLock.status~='down' then
        -- View lock is independent of the spell's target. Self-healing keeps
        -- watching the selected opponent and may finish if that opponent is lost.
        local g=Scene.track(targetLock.ref)
        if g and not A.isDead(g.obj) then
            targetLock.status='locked'
            local yaw,pitch=Scene.lookAngles(g)
            self.controls.yawChange=Turning.delta(camera.getYaw(),yaw,dt)
            self.controls.pitchChange=Turning.delta(camera.getPitch(),pitch,dt)
        else targetLock.status=g and 'down' or 'lost' end
    end
    local info=combatInfo()
    local selected=p.combat.kind=='strike' and info.weapon_info or info.castable
    if p.pursuit then
        local g=Scene.track(p.chain.ref)
        local kind=p.combat.kind=='wait' and p.pursuit.rangeKind or p.pursuitRangeKind or 'touch'
        drivePursuit(p,g,kind,dt)
        context.wait_for_range=not p.pursuit.reason
        if p.pursuit.reason and p.target and context.in_reach==false and p.combat.phase=='prepare'
            and p.pursuit.reason~='target_down' and p.pursuit.reason~='target_lost' then
            finishCombat(p,p.pursuit.reason);return
        end
    end
    context.resource_required=p.spendKind~=nil
    if not selected or selected.available==false then context.unavailable_reason=selected and selected.unavailable_reason or 'nothing_selected' end
    if not p.combat.attempted and p.expectedWeapon and selected
        and (selected.kind~=p.expectedWeapon.kind or selected.name~=p.expectedWeapon.name) then
        context.unavailable_reason='weapon_changed'
    end
    local now=resources(p.ammoRecord)
    local spend=p.spendKind
    local evidence=p.evidenceResources or p.resources
    context.resource_changed=spend and evidence[spend] and (now[spend] or 0)<evidence[spend]-.01 or false
    local attempted=p.combat.attempted
    local command=Combat.step(p.combat,context,dt)
    if not attempted and p.combat.attempted then p.evidenceResources=now end
    p.elapsed=p.combat.elapsed
    active.attack=command.attack
    -- Do not overwrite self.controls.use here: the stock playercontrols script
    -- emits a one-frame casting pulse after the async Use action edge.
    -- Releasing the binding lets that pulse reach mechanics; pause/abort still clear input.
    if command.trigger then input.activateTrigger(command.trigger) end
    if command.done then finishCombat(p) end
end

local function conditionMet(c)
    if c.condition=='fatigue' then
        local f=A.stats.dynamic.fatigue(self)
        return f.current>=math.max(1,(f.base or f.current)+(f.modifier or 0))*(c.percent or 100)/100
    elseif c.condition=='landed' then return A.isOnGround(self) and not A.isSwimming(self)
    elseif c.condition=='animation' then
        local b=bodyState();return not b.animation_busy and not b.recovering
    elseif c.condition=='ui' then return (I.UI.getMode() or 'Gameplay')==c.ui_mode
    elseif c.condition=='controls' then
        local control=c.control or 'controls'
        if control=='looking' then return Player.getControlSwitch(self,Player.CONTROL_SWITCH.Looking) end
        if control=='jumping' then return controlsAllowed() and Player.getControlSwitch(self,Player.CONTROL_SWITCH.Jumping) end
        return controlsAllowed()
    elseif c.condition=='passage' and Terrain then
        local p=Terrain.probe(camera.getYaw()+math.rad(c.bearing_deg or 0),c.meters or 1)
        return not p.obstacle and p.distance>=((c.meters or 1)*Scene.unitsPerMeter-4)
    end
    return false
end
local function onFrame(dt)
    Airborne.sample(core.getSimulationTime(),self.position,Space.key(self.cell),Scene.unitsPerMeter)
    Trajectory.sample(false)
    if not manualActive then Scene.fov(desiredFov) end
    if ready and not pending and not manualActive and bus:get('control_mode')=='manual' then
        clearInput();active=nil;manualActive=true
        if directMovement then I.Controls.overrideMovementControls(false) end
        core.sendGlobalEvent('AstraResume',{})
    end
    lastFrame = lastFrame + 1
    local motorPending=pending and pending.cmd and (pending.start or pending.finalPose)
    if ready and ui._astraUiSnapshot and (motorPending or modalOpen or lastFrame%3==0 or pending and pending.cmd and pending.cmd.op=='choose') then
        local snapshot=uiState()
        modalOpen=snapshot.modal==true
        local notifications={}
        for _,e in ipairs(snapshot.elements) do
            local notification=e.panel=='notification'
            if notification then notifications[e.text]=true end
            if e.role=='text' and (notification and not seenNotifications[e.text]
                or not notification and (#e.text>30 or e.notice) and not seenMessages[e.text]) then
                local last=uiMessages[#uiMessages]
                if last and last.text==e.text and last.notice==e.notice then last.frame=lastFrame
                else uiMessages[#uiMessages+1]={text=e.text,frame=lastFrame,notice=e.notice,source=notification and 'notification' or 'ui_text'} end
                if #uiMessages>20 then
                    table.remove(uiMessages,1)
                end
            end
            if e.role=='text' then seenMessages[e.text]=lastFrame end
        end
        seenNotifications=notifications
        for text,frame in pairs(seenMessages) do if lastFrame-frame>600 then seenMessages[text]=nil end end
    end
    local running = not core.isWorldPaused()
    if running ~= wasRunning or lastFrame%15==0 then
        wasRunning = running
        P.emit({version=1,session=bus:get('session'),event='simulation',active=running,simulation_seconds=core.getSimulationTime()})
    end
    bus:set('can_save', ready and Player.isCharGenFinished(self) and not (A.isDead and A.isDead(self))
        and not modalOpen and I.UI.getMode() == nil and core.isWorldPaused())
    if bus:get('cancel') then
        bus:set('cancel',false)
        pausedSneak=false
        if pending and pending.phase=='pausing' then clearInput()
        elseif pending and pending.combat then finishCombat(pending,'cancelled')
        else pause(pending and pending.cmd, {paused=true,reason='cancelled',elapsed=pending and pending.elapsed or 0}) end
    end
    -- Native tutorial/message boxes can demand input while Lua still reports
    -- Gameplay, even with zero simulation dt. Check every action frame, before
    -- resuming/running/releasing/pausing branches and before any further input.
    if modalOpen then interruptForModal() end
    if pending then
        if pending.phase == 'pausing' then
            if pauseAck == pending.token and core.isWorldPaused() then
                settle=settle+1
                if settle >= 3 then finish() end
            end
        elseif pending.phase=='releasing' then
            local p=pending
            if core.isWorldPaused() or I.UI.getMode() or (lastFrame>p.releaseFrame and dt>0) then
                p.result.elapsed=(p.result.elapsed or p.elapsed)+dt
                p.result.released=true
                pause(p.cmd,p.result)
            end
        elseif pending.phase == 'running' then
            local p = pending
            if p.aerial and Space.key(self.cell)==p.start.cell then Airborne.update(p.aerial,A.isOnGround(self),A.isSwimming(self),self.position.z,ownHealth()) end
            if not p.lastProgress or core.getRealTime()-p.lastProgress>=.5 then
                p.lastProgress=core.getRealTime()
                local progress={operation=p.cmd.op,elapsed=p.elapsed or 0,phase=p.phase}
                progress._atlas_travel=Trajectory.flush()
                if p.navigator then progress.navigation=require('scripts.astrabridge.navigation').report(p.navigator) end
                P.emit({version=1,session=bus:get('session'),event='progress',result=progress})
            end
            local guardReason=Guards.check(p.cmd.args._guard,core.getSimulationTime(),A.stats and A.stats.dynamic and A.stats.dynamic.health(self))
            if guardReason then
                if p.combat then finishCombat(p,guardReason) else pause(p.cmd,{paused=true,reason=guardReason,elapsed=p.elapsed}) end
                return
            end
            local damage=0
            if p.lastHealth then
                local health=ownHealth();damage=p.lastHealth-health;p.lastHealth=health
            end
            if p.start and Space.key(self.cell)~=p.start.cell then
                targetLock=nil;routes={};walkingRoute=nil
                if p.combat then finishCombat(p,'location_changed')
                else pause(p.cmd,{paused=true,elapsed=p.elapsed,reason='location_changed'}) end
            elseif A.isDead and A.isDead(self) then
                if p.combat then finishCombat(p,'player_down')
                else pause(p.cmd,{paused=true,elapsed=p.elapsed,reason='player_down'}) end
            elseif p.waitCondition and not p.aerial and conditionMet(p.waitCondition) then pause(p.cmd,{paused=true,elapsed=p.elapsed,reason='condition_met'})
            elseif p.interactionSubmitted then
                p.elapsed=p.elapsed+dt
                if p.elapsed-p.interactionSubmitted>=.2 or I.UI.getMode() then pause(p.cmd,{paused=true,elapsed=p.elapsed,reason='completed'}) end
            elseif p.combat then combatFrame(p,dt)
            elseif I.UI.getMode() then pause(p.cmd,{paused=true,elapsed=p.elapsed,reason='ui_open'})
            elseif damage>.01 then pause(p.cmd,{paused=true,reason=A.isDead(self) and 'player_down' or 'player_hurt',damage_taken=math.floor(damage*100+.5)/100})
            elseif not controlsAllowed() and (p.kind=='approach' or p.kind=='move_local' or p.kind=='walk' or p.kind=='evade'
                or p.aerial and p.aerial.kind~='landed' or active and ((active.move or 0)~=0 or (active.strafe or 0)~=0)) then
                pause(p.cmd,{paused=true,reason='player_controls_disabled'})
            elseif p.navigator and p.navigator.waterWalking and not Mobility.has('WaterWalking') then pause(p.cmd,{paused=true,reason='water_walking_ended'})
            elseif p.navigator and p.navigator.mode=='air' and not Mobility.has('Levitate') and not A.isOnGround(self) and not A.isSwimming(self) then pause(p.cmd,{paused=true,reason='levitation_ended'})
            elseif core.getRealTime() > p.deadline then pause(p.cmd,{paused=true,elapsed=p.elapsed,reason='wall_time_limit'})
            elseif core.isWorldPaused() then
                -- Native message boxes do not necessarily appear in I.UI.modes.
                p.pausedFrames = (p.pausedFrames or 0) + 1
                if p.pausedFrames >= 3 then pause(p.cmd,{paused=true,elapsed=p.elapsed,reason='game_paused'}) end
            elseif not core.isWorldPaused() then
                p.pausedFrames = 0
                if p.viewpointGoal then
                    local d=p.viewpointGoal-self.position
                    p.elapsed=p.elapsed+dt
                    if d:length()<4 then p.viewpointGoal=nil;stopMovement();return end
                    if p.elapsed-p.viewpointStart>1.5 or p.elapsed>=p.seconds or Terrain.contact(self.position,p.viewpointGoal) then
                        pause(p.cmd,{paused=true,reason='viewpoint_blocked'});return
                    end
                    local y=camera.getYaw();local scale=math.min(1,d:length()/35)
                    active.move=scale*(d.x*math.sin(y)+d.y*math.cos(y))/math.max(1,d:length())
                    active.strafe=scale*(d.x*math.cos(y)-d.y*math.sin(y))/math.max(1,d:length())
                    return
                end
                if p.aerial and p.aerial.kind~='act' then
                    local reason=Airborne.reason(p.aerial,A.isOnGround(self),A.isSwimming(self),Mobility.has('Levitate'),p.elapsed,p.seconds)
                    if (reason=='landed' or reason=='condition_met') and p.aerial.airborne_observed and not p.landingReason then
                        -- Physics reports support one update before mechanics applies
                        -- fall damage. Release input now, then let that update finish.
                        p.landingReason=reason;p.landingTime=p.elapsed
                        stopMovement();self.controls.jump=false;active.trigger=nil
                    end
                    if p.landingReason then
                        if p.elapsed-p.landingTime<.05 then p.elapsed=p.elapsed+dt;return end
                        reason=A.isOnGround(self) and not A.isSwimming(self) and p.landingReason or 'landing_unstable'
                    end
                    if reason then pause(p.cmd,{paused=true,reason=reason,elapsed=p.elapsed});return end
                    if p.aerial.kind=='jump' and not Player.getControlSwitch(self,Player.CONTROL_SWITCH.Jumping) and not p.triggered then
                        pause(p.cmd,{paused=true,reason='player_controls_disabled'});return
                    end
                end
                local lockGoal
                if targetLock and targetLock.status~='down' then
                    lockGoal=lockedTarget()
                    if not lockGoal then
                        active.attack=false;active.move=0;active.strafe=0
                        self.controls.use=self.ATTACK_TYPE.NoAttack
                        self.controls.movement,self.controls.sideMovement=0,0
                        p.missingTarget=(p.missingTarget or 0)+dt
                        if targetLock.status=='down' or p.missingTarget>=.35 then
                            pause(p.cmd,{paused=true,elapsed=p.elapsed,reason=targetLock.status=='down' and 'target_down' or 'target_lost'})
                        else p.elapsed=p.elapsed+dt end
                        return
                    end
                    p.missingTarget=0
                    if not p.kind then active.move=p.requestedMove;active.strafe=p.requestedStrafe end
                end
                if p.kind then
                    if p.kind=='evade' then
                        driveEvasion(p,lockGoal,dt)
                        p.elapsed=p.evade.elapsed
                        if p.evade.reason then pause(p.cmd,{paused=true,reason=p.evade.reason}) end
                        return
                    end
                    if p.kind=='walk' then
                        local N=require('scripts.astrabridge.navigation')
                        if N.reached(p.navigator) and N.canFinish(p.navigator) then pause(p.cmd,{paused=true,reason='arrived'});return end
                        local waypoint=require('scripts.astrabridge.navigation').step(p.navigator,nil,dt)
                        if not waypoint then pause(p.cmd,{paused=true,reason=p.navigator.endpointMismatch and 'endpoint_mismatch'
                            or p.navigator.status=='height_mismatch' and 'height_mismatch'
                            or p.navigator.path and 'path_end_out_of_reach' or 'no_path'});return end
                        if p.navigator.status=='waiting' then
                            stopMovement();p.elapsed=p.elapsed+dt;p.progressTime=p.elapsed
                            if p.elapsed>=(p.maxSeconds or 8) then pause(p.cmd,{paused=true,reason='step_limit'}) end
                            return
                        end
                        local yaw,pitch,fraction=N.motion(p.navigator,waypoint,dt,active.run,camera.getYaw())
                        self.controls.yawChange=Turning.delta(camera.getYaw(),yaw,dt)
                        self.controls.pitchChange=Turning.delta(camera.getPitch(),pitch,dt)
                        local turnTolerance=p.navigator.detour and 5 or 20
                        active.move=math.abs(Scene.angle(yaw-camera.getYaw()))<math.rad(turnTolerance)
                            and math.abs(pitch-camera.getPitch())<math.rad(8) and fraction or 0
                        if active.move==0 then stopMovement() end
                        p.elapsed=p.elapsed+dt
                        local stall=N.stalled(p.navigator,p.elapsed)
                        if stall then
                            if N.recover(p.navigator,yaw) then require('scripts.astrabridge.progress').recover(p.navigator,p.elapsed)
                            else pause(p.cmd,{paused=true,reason=p.navigator.failureReason or 'blocked'});return end
                        end
                        if p.elapsed>=(p.maxSeconds or 8) then pause(p.cmd,{paused=true,reason='step_limit'});return end
                        return
                    end
                    local yaw,pitch=p.start.yaw,p.start.pitch
                    if lockGoal then yaw,pitch=Scene.lookAngles(lockGoal) end
                    local reached=false
                    local moveFraction=1
                    local aimTarget=lockGoal
                    if p.kind~='move_local' then
                        local g=Scene.resolve(p.target,true)
                        local visible=g~=nil
                        if visible then p.lastVisible=p.elapsed end
                        if not g and p.navigator and (not p.navigator.movingTarget or p.elapsed-(p.lastVisible or 0)<4) then
                            g=p.navigator.lastGoal
                        end
                        if not g then pause(p.cmd,{paused=true,reason='target_lost'});return end
                        if p.kind=='track' and types.Actor.objectIsInstance(g.obj) and A.isDead(g.obj) then
                            pause(p.cmd,{paused=true,reason='target_down'});return
                        end
                        yaw,pitch=Scene.lookAngles(g)
                        aimTarget=g
                        -- Leave room for the small eye-position change when
                        -- focus tilts upward toward a hatch or downward to loot.
                        reached=visible and Scene.reach(g,p.kind=='approach' and .85 or nil)
                        if p.kind=='approach' and p.reachKind and p.reachKind~='activate' then
                            reached=visible and ui._astraTargetReach(g.obj)[p.reachKind..'_in_reach']
                        end
                        if p.kind=='approach' and reached then
                            if p.interact then p.kind='focus';p.navigator=nil;stopMovement()
                            else pause(p.cmd,{paused=true,reason='within_reach'});return end
                        end
                        if p.kind=='focus' and math.abs(pitch)>math.rad(80) then
                            if adjustViewpoint(p) then return end
                            pause(p.cmd,{paused=true,reason='viewpoint_adjustment_needed'});return
                        end
                        if p.navigator then
                            local waypoint=require('scripts.astrabridge.navigation').step(p.navigator,visible and g or nil,dt)
                            if p.navigator.status=='waiting' then
                                stopMovement();p.elapsed=p.elapsed+dt;p.progressTime=p.elapsed
                                if p.elapsed>=p.seconds then pause(p.cmd,{paused=true,reason='step_limit'}) end
                                return
                            end
                            if not reached and not p.navigator.path then
                                pause(p.cmd,{paused=true,reason=p.navigator.status=='no_path' and 'no_path' or 'navigation_unavailable'});return
                            end
                            if not reached and not waypoint then
                                pause(p.cmd,{paused=true,reason='path_end_out_of_reach'});return
                            end
                            if not reached and waypoint then
                                yaw,pitch,moveFraction=require('scripts.astrabridge.navigation').motion(p.navigator,waypoint,dt,active.run,camera.getYaw())
                            elseif not visible then pause(p.cmd,{paused=true,reason='target_lost'});return end
                        end
                    end
                    local ye=Scene.angle(yaw-camera.getYaw())
                    local pe=pitch-camera.getPitch()
                    self.controls.yawChange=Turning.delta(camera.getYaw(),yaw,dt)
                    self.controls.pitchChange=Turning.delta(camera.getPitch(),pitch,dt)
                    local aimed
                    if aimTarget then aimed=Scene.aimedAt(aimTarget)
                    else aimed=math.abs(ye)<math.rad(.5) and math.abs(pe)<math.rad(.5) end
                    if p.kind=='focus' then
                        -- Rendering rays and the engine's activation camera
                        -- settle on different update stages. Finish the turn,
                        -- then allow two frames before checking the native ray.
                        aimed=aimed and math.abs(ye)<math.rad(.5) and math.abs(pe)<math.rad(.5)
                        p.aimFrames=aimed and (p.aimFrames or 0)+1 or 0
                        aimed=aimed and p.aimFrames>=2
                    end
                    active.move,active.strafe=0,0
                    if p.kind=='track' then
                        active.attack=p.attack and (Scene.combatAligned and Scene.combatAligned(aimTarget) or aimed)
                        if p.elapsed>=p.seconds then finishStep(p,{paused=true,reason='tracked',elapsed=p.elapsed});return end
                    end
                    if p.kind=='focus' and not aimed and (p.aimFrames or 0)==0 and p.elapsed>1 and math.abs(ye)<math.rad(1) and math.abs(pe)<math.rad(1) then
                        if adjustViewpoint(p) then return end
                        pause(p.cmd,{paused=true,reason='target_obstructed'});return
                    end
                    if p.kind=='focus' and aimed and not (p.waitReady and Scene.lootReady(aimTarget)==false) then
                        if p.interact then
                            if not Scene.reach(aimTarget) then pause(p.cmd,{paused=true,reason='out_of_reach'});return end
                            if not Scene.crosshair(aimTarget) then
                                if adjustViewpoint(p) then return end
                                pause(p.cmd,{paused=true,reason='target_not_aimed'});return
                            end
                            if not ui._astraActivate then pause(p.cmd,nil,'native_ui_unavailable');return end
                            p.expected={cell=Space.key(self.cell),ref=p.target}
                            if types.Item and types.Item.objectIsInstance(aimTarget.obj) then
                                p.expected.item=aimTarget.obj.recordId;p.expected.count=A.inventory(self):countOf(p.expected.item)
                            end
                            if types.Door and types.Door.objectIsInstance(aimTarget.obj) then
                                p.expected.door=aimTarget.obj;p.expected.doorState=types.Door.getDoorState(aimTarget.obj)
                                p.expected.doorOpen=types.Door.isOpen(aimTarget.obj)
                            end
                            stopMovement()
                            if not ui._astraActivate(aimTarget.obj) then
                                p.expected=nil;pause(p.cmd,{paused=true,reason='target_not_aimed'});return
                            end
                            p.interactionSubmitted=p.elapsed;return
                        end
                        pause(p.cmd,{paused=true,reason='focused'});return
                    elseif p.kind=='approach' then
                        if math.abs(ye)<math.rad(20) and math.abs(pe)<math.rad(8) and not reached then active.move=moveFraction end
                    elseif p.kind=='move_local' then
                        local d=p.destination-self.position
                        if math.sqrt(d.x*d.x+d.y*d.y)<4 then pause(p.cmd,{paused=true,reason='arrived'});return end
                        local y=camera.getYaw()
                        active.move=math.max(-1,math.min(1,(d.x*math.sin(y)+d.y*math.cos(y))/80))
                        active.strafe=math.max(-1,math.min(1,(d.x*math.cos(y)-d.y*math.sin(y))/80))
                    end
                    if active.move==0 and active.strafe==0 then stopMovement() end
                    p.elapsed=p.elapsed+dt
                    if p.kind~='focus' and p.kind~='track' then
                        local N=require('scripts.astrabridge.navigation')
                        local stall
                        if p.navigator then stall=N.stalled(p.navigator,p.elapsed)
                        elseif p.destination then stall=require('scripts.astrabridge.progress').update(p,p.elapsed,
                            (p.destination-self.position):length(),self.position.x,self.position.y,self.position.z) end
                        if stall then
                            if p.navigator and N.recover(p.navigator,yaw) then require('scripts.astrabridge.progress').recover(p.navigator,p.elapsed)
                            else pause(p.cmd,{paused=true,reason=stall});return end
                        end
                    end
                    if p.kind~='track' and p.elapsed>p.seconds then pause(p.cmd,{paused=true,reason='step_limit'});return end
                    return
                end
                if not p.triggered then
                    if active.target then
                        local g=Scene.resolve(active.target,true)
                        if not g or not Scene.reach(g) then pause(p.cmd,{paused=true,reason='target_lost'});return end
                        local yaw,pitch=Scene.lookAngles(g)
                        p.yaw,p.pitch=yaw,pitch
                        self.controls.yawChange=Turning.delta(camera.getYaw(),yaw,dt)
                        self.controls.pitchChange=Turning.delta(camera.getPitch(),pitch,dt)
                        if not Scene.crosshair(g) then return end
                    end
                    p.triggered = true
                    if active.trigger == 'Activate' then
                        if ui._astraActivate then
                            if not ui._astraActivate() then pause(p.cmd,nil,'action_unavailable');return end
                        else
                            p.nativeWait = true
                            p.nativeDeadline = core.getRealTime()+2
                            P.emit({version=1,session=p.cmd.session,id=p.cmd.id,event='native_input',name='Activate'})
                        end
                    elseif active.trigger=='Jump' and directMovement then
                        p.jumpRequested=Player.getControlSwitch(self,Player.CONTROL_SWITCH.Jumping)
                    elseif active.trigger then input.activateTrigger(active.trigger) end
                    if Space.key(self.cell)~=p.start.cell then
                        targetLock=nil;routes={};walkingRoute=nil
                        pause(p.cmd,{paused=true,elapsed=p.elapsed,reason='location_changed'});return
                    end
                end
                if p.nativeWait then
                    if active.target then
                        local g=Scene.resolve(active.target,true)
                        if not g or not Scene.reach(g) then pause(p.cmd,{paused=true,reason='target_lost'});return end
                        local yaw,pitch=Scene.lookAngles(g)
                        self.controls.yawChange=Turning.delta(camera.getYaw(),yaw,dt)
                        self.controls.pitchChange=Turning.delta(camera.getPitch(),pitch,dt)
                    end
                    local ok,ack = pcall(P.inputAck,p.cmd.session,p.cmd.id)
                    if ok and ack ~= nil then
                        p.nativeWait = false
                        if not ack then pause(p.cmd,nil,'input_failed'); return end
                    elseif core.getRealTime() > p.nativeDeadline then
                        pause(p.cmd,nil,'input_timeout'); return
                    else return end
                end
                if lockGoal then p.yaw,p.pitch=Scene.lookAngles(lockGoal) end
                local turnYaw=p.turnYaw or lockGoal or active.target
                local turnPitch=p.turnPitch or lockGoal or active.target
                local ye=turnYaw and Scene.angle(p.yaw-camera.getYaw()) or 0
                local pe=turnPitch and p.pitch-camera.getPitch() or 0
                if lockGoal then active.attack=p.requestedAttack and (Scene.combatAligned and Scene.combatAligned(lockGoal) or Scene.aimedAt(lockGoal)) end
                if p.elapsed>=p.seconds and (lockGoal or math.abs(ye)<math.rad(.5) and math.abs(pe)<math.rad(.5)) then
                    finishStep(p,{paused=true,elapsed=p.elapsed,reason=p.waitCondition and 'condition_timeout' or 'duration'});return
                end
                if p.elapsed>=p.seconds then active.move=0;active.strafe=0;active.attack=false end
                if p.elapsed>math.max(p.seconds,1.5)+1 then
                    finishStep(p,{paused=true,elapsed=p.elapsed,reason='turn_limit'});return
                end
                if Player.getControlSwitch(self,Player.CONTROL_SWITCH.Looking) then
                    self.controls.yawChange = turnYaw and Turning.delta(camera.getYaw(),p.yaw,dt) or 0
                    self.controls.pitchChange = turnPitch and Turning.delta(camera.getPitch(),p.pitch,dt) or 0
                end
                p.elapsed = p.elapsed + dt
            end
        elseif core.getRealTime() > pending.deadline then pause(pending.cmd,nil,'resume_timeout') end
    end
    local cmd = bus:getCopy('request')
    if cmd and ready and not pending then
        local key = cmd.session .. ':' .. cmd.id
        if key ~= requestKey then
            requestKey = key
            local ok, err = pcall(dispatch,cmd)
            if not ok then print('ASTRA_DIAGNOSTIC dispatch: '..tostring(err)); pause(cmd,nil,'operation_failed') end
        end
    end
end
local function reset()
    manualActive=false
    if directMovement then I.Controls.overrideMovementControls(true) end
    require('scripts.astrabridge.camera_policy').apply()
    epoch = (bus:get('epoch') or 0)+1
    Scene.reset(namespace())
    Trajectory.reset(namespace())
    Airborne.reset()
    if Terrain then Terrain.reset(namespace()) end
    bus:set('epoch',epoch)
    bus:set('ready',false)
    bus:set('cancel',false)
    bus:set('request',nil)
    bus:set('response',nil)
    ready, requestKey,targetLock = false, nil,nil
    refs={};ownedRefs={}
    routes={}
    walkingRoute=nil
    pausedSneak=false
    uiMessages,seenMessages=P.array(),{}
    seenNotifications={}
    modalOpen=false
    invalidate()
    pause(nil)
end
return {
    engineHandlers={
    onSave=function() return {recognition_instances=Scene.saveRecognition()} end,
    onLoad=function(data) Scene.loadRecognition(data and data.recognition_instances) end,
    onFrame=function(dt)
        local ok, err = pcall(function()
            onFrame(dt)
            if directMovement and not manualActive then
                local live=active and pending and pending.phase=='running' and not pending.nativeWait
                    and not core.isWorldPaused() and not I.UI.getMode() and controlsAllowed()
                MovementInput.apply(self.controls,active,live,pausedSneak,pending and pending.jumpRequested)
                if pending then pending.jumpRequested=nil end
            end
        end)
        if not ok then
            print('ASTRA_DIAGNOSTIC frame: '..tostring(err))
            local cmd = pending and pending.cmd
            clearInput()
            if ui._astraPause then ui._astraPause() end
            core.sendGlobalEvent('AstraPause',{})
            if cmd then bus:set('response',{id=cmd.id,session=cmd.session,error='observation_failed'}) end
            pending = nil
        end
    end},
    eventHandlers={
        AstraReset=reset,
        AstraPaused=function(data) pauseAck=data.token or -1 end,
        AstraResumed=function(data)
            if pending and pending.phase == 'resuming' and pending.cmd.id == data.id then pending.phase='running' end
        end,
    },
}
