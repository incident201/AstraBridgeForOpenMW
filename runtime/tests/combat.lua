package.path='mod/?.lua;'..package.path
local C=require('scripts.astrabridge.combat')
local F=require('scripts.astrabridge.effect_facts')
local ids={DamageHealth='private_damage',DrainHealth='private_drain',RestoreHealth='private_heal'}
assert(F.healthKind('private_damage',ids)=='damage' and F.healthKind('private_drain',ids)=='temporary_reduction')
assert(F.healthKind('private_heal',ids)=='healing' and F.healthKind('unknown',ids)==nil)
assert(C.isRecoveryGroup('hit1') and C.isRecoveryGroup('swimhit2') and C.isRecoveryGroup('knockdown'))
assert(not C.isRecoveryGroup('spellcast') and not C.isRecoveryGroup('deathknockdown'))
local function context(changes)
    local c={stance='weapon',busy=false,can_move=true,in_reach=true,aligned=true}
    for k,v in pairs(changes or {}) do c[k]=v end
    return c
end
local s=C.new('strike',.8)
local stagger=C.new('cast')
for _=1,10 do assert(not C.step(stagger,context({stance='spell',recovering=true}),.1).attack) end
assert(not stagger.attempted and not stagger.animationObserved,'a hit reaction is neither readiness nor a completed cast')
for _=1,3 do C.step(stagger,context({stance='spell'}),.1)end
assert(stagger.attempted,'the queued use resumes once recovery is over')
local continued=C.new('strike',.15,true)
assert(not C.step(continued,context({busy=true}),.1).attack,'continued steps still respect animation busy state')
assert(C.step(continued,context(),.1).attack,'confirmed release permits the next same-kind step without an artificial idle gap')
local waiting=C.new('wait',.6)
for _=1,2 do local out=C.step(waiting,context({can_move=false,busy=true}),.2);assert(not out.attack and not out.trigger and not out.done)end
assert(C.step(waiting,context({can_move=false,busy=true}),.2).done and not waiting.attempted)
assert(C.report(waiting).outcome=='wait_completed','a wait advances time without trying to cast or change stance')
waiting=C.new('wait',2);assert(C.step(waiting,context({target_down=true}),.2).reason=='target_down')
local closing=C.new('strike',.15)
for _=1,6 do assert(not C.step(closing,context({in_reach=false,wait_for_range=true}),.2).done)end
assert(not closing.attempted and C.step(closing,context(),.2).attack,'explicit forward movement may close the distance before the first hit')
closing=C.new('strike',.15)
for _=1,40 do assert(not C.step(closing,context({in_reach=false,wait_for_range=true}),.2).done)end
assert(C.step(closing,context(),.2).attack,'approach time belongs to the overall queue budget, not the six-second use budget')
assert(C.step(s,context({stance='nothing'}),.1).trigger=='ToggleWeapon')
assert(not C.step(s,context({busy=true}),.3).attack)
assert(not C.step(s,context(),.2).attack)
assert(not C.step(s,context(),.2).attack)
assert(C.step(s,context(),.2).attack)
assert(C.step(s,context({busy=true}),.4).attack)
assert(not C.step(s,context({busy=true}),.4).attack)
assert(not C.step(s,context({busy=true}),.8).done,'must finish the recovery animation')
assert(not C.step(s,context(),.1).done)
assert(C.step(s,context(),.2).done)
local r=C.report(s)
assert(r.reason=='completed' and r.released and r.animation_complete and r.animation_observed)
for _,dt in ipairs({1/60,.2}) do
    local cast=C.new('cast')
    local previous,pulses,done=false,0,false
    for i=1,1000 do
        local busy=cast.attempted and cast.elapsed<2
        local out=C.step(cast,context({stance='spell',busy=busy,resource_changed=cast.attempted}),dt)
        if out.attack and not previous then pulses=pulses+1 end
        previous=out.attack
        if out.done then done=true;break end
    end
    assert(done and pulses==1 and cast.reason=='completed','one cast at both high and low FPS')
end
s=C.new('cast')
for _=1,30 do
    local out=C.step(s,context({stance='spell',resource_changed=s.attempted}),.1)
    if out.done then break end
end
assert(s.reason=='completed' and not s.animationObserved,'instant enchantments need resource evidence')
s=C.new('cast')
for _=1,30 do if C.step(s,context({stance='spell'}),.1).done then break end end
assert(s.reason=='action_not_started','do not silently retry an ignored input')
local drawing=C.new('cast')
for _=1,50 do
    local out=C.step(drawing,context({stance='spell',busy=drawing.attempted and drawing.elapsed<2,
        animation_active=false}),.1)
    if out.done then break end
end
assert(drawing.reason=='action_not_started','drawing a weapon is not proof of a spell animation, even for a free spell')
for _,spent in ipairs({false,true}) do
    local cast=C.new('cast')
    for _=1,50 do
        local out=C.step(cast,context({stance='spell',busy=cast.attempted and cast.elapsed<2,
            resource_required=true,resource_changed=spent and cast.attempted and cast.elapsed<1.5}),.1)
        if out.done then break end
    end
    assert(cast.reason==(spent and 'completed' or 'cast_not_confirmed'),
        'a paid cast requires observed spending; remember it even if regeneration later conceals it')
end
for _,case in ipairs({{in_reach=false,reason='out_of_reach'},{target_lost=true,reason='target_lost'},
    {unavailable_reason='insufficient_magicka',reason='insufficient_magicka'}}) do
    s=C.new('strike');local out
    for _=1,3 do out=C.step(s,context(case),.2) end
    assert(out.done and out.reason==case.reason and not s.attempted)
end
s=C.new('strike');for _=1,3 do C.step(s,context(),.2) end
assert(C.step(s,context({target_lost=true,busy=true}),.1).done)
assert(s.reason=='target_lost' and not C.report(s).animation_complete)
s=C.new('cast')
for _=1,40 do if C.step(s,context({stance='spell',busy=true}),.2).done then break end end
assert(s.reason=='step_limit' and not s.attempted)
print('Combat phases, input pulses, preparation/recovery, resource evidence and interruption passed')
