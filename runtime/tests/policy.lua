-- Execute the real player adapter against fabricated engine data; no game assets needed.
package.path = 'mod/?.lua;' .. package.path
local busData, paused, now, mode = {}, true, 0, nil
local realStep=.02
local allow = {}
local player, events = nil, {}
local bus = {
    get=function(_,k) return busData[k] end,
    getCopy=function(_,k) return busData[k] end,
    set=function(_,k,v) busData[k]=v end,
}
local controls = {}
local position=setmetatable({x=0,y=0,z=0},{__sub=function()return {x=0,y=0,z=0,length=function()return 0 end}end})
local object = {position=position,controls=controls, ATTACK_TYPE={NoAttack=0}, object={},cell={id='private',displayName='Room'}}
local item = {isValid=function()return true end,count=2, id='SECRET_REFERENCE', position={x=99}, type={}}
item.type.record=function() return {name='Зелье',id='SECRET_RECORD',effects={'SECRET_EFFECT'}} end
local bindings={}
package.preload['openmw.camera']=function() return {getYaw=function()return 0 end,getPitch=function()return 0 end} end
local uiApi={}
package.preload['openmw.ui']=function()return uiApi end
package.preload['openmw.util']=function()return {} end
package.preload['scripts.astrabridge.scene']=function() return {
    unitsPerMeter=70,identity=function()return {details_visible=false}end,
    reset=function()end,fov=function()end,pose=function()return {yaw=0,pitch=0,cell='private'}end,
    report=function()return {moved_m=0}end,angle=function(x)return x end,
    orientation=function()return {}end,observe=function()return {objects={}}end,
} end
package.preload['openmw.storage']=function() return {playerSection=function() return bus end} end
package.preload['openmw.self']=function() return object end
package.preload['openmw.async']=function() return {callback=function(_,f) return f end} end
package.preload['openmw.vfs']=function() return {} end
package.preload['openmw.markup']=function() return {} end
package.preload['openmw.input']=function() return {
    bindAction=function(name,callback) bindings[name]=callback end,
    activateTrigger=function() end,
} end
local stats={dynamic={},attributes={},level=function() return {current=1} end}
for _,n in ipairs({'health','magicka','fatigue'}) do stats.dynamic[n]=function() return {current=5,base=10,modifier=0} end end
for _,n in ipairs({'strength','intelligence','willpower','agility','speed','endurance','personality','luck'}) do
    stats.attributes[n]=function() return {modified=40} end
end
package.preload['openmw.types']=function() return {
    Actor={stats=stats,inventory=function() return {getAll=function() return {item} end,countOf=function()return 7 end} end,
        hasEquipped=function() return false end,getEncumbrance=function() return 2 end,getCapacity=function() return 100 end},
    Player={CONTROL_SWITCH={Looking=1,Controls=2},getControlSwitch=function() return true end,
        getBirthSign=function()return 'secret_sign'end,birthSigns={records={secret_sign={name='Воин'}}},
        getCrimeLevel=function()return 0 end,journal=function()return {journalTextEntries={}}end,
        isCharGenFinished=function() return true end},
    NPC={record=function()return {name='Test',race='secret_race',class='secret_class'}end,
        races={records={secret_race={name='Данмер'}}},classes={records={secret_class={name='Воин'}}},
        stats={reputation=function()return {current=1}end}},
} end
package.preload['openmw.interfaces']=function() return {UI={
    MODE={Interface='Interface'},getMode=function() return mode end,
    getWindowsForMode=function() return allow end,
}} end
package.preload['openmw.core']=function() return {
    getGMST=function(name)return name end,
    isWorldPaused=function() return paused end,
    getRealTime=function() return now end, getGameTime=function()return 0 end, getSimulationTime=function()return now end,
    sendGlobalEvent=function(name,data) events[#events+1]={name,data} end,
} end
player=require('scripts.astrabridge.player')
local P=require('scripts.astrabridge.protocol')
local function tick()
    now=now+realStep
    local queue=events;events={}
    for _,e in ipairs(queue) do
        if e[1]=='AstraPause' then paused=true;player.eventHandlers.AstraPaused(e[2]) end
        if e[1]=='AstraResume' then paused=false;player.eventHandlers.AstraResumed(e[2]) end
    end
    player.engineHandlers.onFrame(paused and 0 or .02)
end
player.eventHandlers.AstraReset()
for _=1,8 do tick() end
assert(busData.ready and paused)
local id=0
local function command(op,args)
    id=id+1
    busData.response=nil
    busData.request={id=id,session='test',op=op,args=args or {}}
    for _=1,200 do tick();if busData.response then return busData.response end end
    error('no response')
end
assert(command('inspect',{view='inventory'}).error=='view_unavailable')
assert(command('inspect',{view='character'}).error=='view_unavailable')
assert(command('chain',{actions={{op='wait',seconds=1}}}).error=='view_unavailable')
assert(command('strike',{air=true}).error=='view_unavailable')
assert(command('cast',{}).error=='view_unavailable')
allow={Inventory='Inventory',Stats='Stats',Magic='Magic'}
local character=command('inspect',{view='character'}).result
assert(character.player_name=='Test' and character.race=='Данмер' and character.birth_sign=='Воин')
assert(character.carried_weight==2 and character.capacity==100 and not character.overencumbered)
assert(#character.stats.attribute_details==8 and character.stats.attributes.strength==40)
assert(not P.encode(character):find('secret_'),'character summary must not leak record identifiers')
local result=command('inspect',{view='inventory'}).result
local encoded=P.encode(result)
assert(not encoded:find('SECRET') and not encoded:find('position') and not encoded:find('effects'))
assert(result.items[1].name=='Зелье' and result.items[1].count==2)
local old=result.items[1].ref
local action=command('act',{move=1,seconds=.12})
assert(not action.error and paused and controls.movement==0)
assert(action.result.elapsed>=.12 and action.result.elapsed<.18)
assert(not command('use_item',{ref=old}).error,'owned item refs survive actions and repeated inspection')
assert(command('inspect',{view='inventory'}).result.items[1].ref==old)
assert(command('act',{seconds=math.huge}).error=='operation_failed' and paused)
assert(not command('act',{seconds=.2,sneak=true}).error)
assert(controls.sneak and bindings.Sneak(0,false),'crouch posture must survive the thinking pause')
assert(not command('observe').error and controls.sneak)
assert(not command('look',{pitch_deg=0}).error and controls.sneak,'looking must preserve crouch posture')
assert(not command('stop').error and not controls.sneak)
realStep=1
local limited=command('act',{move=1,seconds=3})
assert(not limited.error and limited.result.reason=='wall_time_limit')
assert(limited.result.elapsed<3 and limited.result.motion and paused and controls.movement==0)
print('Lua projection, access gating, stale handles and autonomous pause passed')

-- Semantic dialogue content must survive viewport clipping and namespacing.
mode='Dialogue'
uiApi._astraUiSnapshot=function()
    return {revision='abc',modal=false,dialogue={text='Earlier answer\nLatest answer'},elements={
        {ref='ui_abc_0',role='text',text='Latest answer',rect={0,0,50,20},enabled=false},
        {ref='ui_abc_1',role='button',text='Available topic',panel='dialogue_topics',screen_visible=false,enabled=true},
        {ref='ui_abc_2',role='button',text='Disabled topic',panel='dialogue_topics',screen_visible=false,enabled=false},
    }}
end
local chosen,hovered,wheel
uiApi._astraUiChoose=function(ref)chosen=ref;return true end
uiApi._astraUiHover=function(ref)hovered=ref;return true end
uiApi._astraUiScroll=function(steps)wheel=steps;return true end
local dialog=command('ui').result
assert(dialog.text=='Earlier answer\nLatest answer')
assert(#dialog.dialogue.topics==2)
local available=dialog.dialogue.topics[1]
assert(not available.rect and available.screen_visible==false)
assert(available.ref==dialog.elements[2].ref and available.ref~='ui_abc_1')
assert(not command('choose',{ref=available.ref}).error and chosen=='ui_abc_1')
assert(command('choose',{ref=dialog.dialogue.topics[2].ref}).error=='ui_control_disabled')
assert(command('ui_hover',{ref=available.ref}).error=='ui_element_offscreen' and not hovered)
assert(not command('ui_hover',{ref=dialog.elements[1].ref}).error and hovered=='ui_abc_0')
assert(not command('ui_scroll',{steps=-4}).error and wheel==-4)
assert(command('ui_scroll',{steps=1.5}).error=='invalid_arguments')
assert(command('choose',{ref='ui_old_1'}).error=='stale_ui_ref')
print('dialogue accessibility policy ok')
