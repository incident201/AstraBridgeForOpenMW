-- One bounded use of the normal input button. No damage/stat mutations and no retry.
local M={}
function M.isRecoveryGroup(name)
    return type(name)=='string' and (name:match('^hit%d*$')~=nil or name:match('^swimhit%d*$')~=nil
        or name=='knockdown' or name=='knockout' or name=='swimknockdown' or name=='swimknockout')
end
function M.new(kind,charge,continued)
    return {kind=kind,charge=charge or .8,waitDuration=kind=='wait' and (charge or .5) or nil,
        phase=kind=='wait' and 'wait' or 'prepare',elapsed=0,phaseTime=0,
        attempted=false,animationObserved=false,released=false,quiet=0,readyFrames=0,
        requiredQuiet=continued and 0 or .2,requiredReadyFrames=continued and 1 or 3}
end
local function finish(s,reason)
    s.reason=reason;s.phase='done'
    return {attack=false,done=true,reason=reason}
end
function M.abort(s,reason)return finish(s,reason)end
function M.step(s,c,dt)
    if s.phase=='done' then return {attack=false,done=true,reason=s.reason} end
    s.elapsed=s.elapsed+dt;s.phaseTime=s.phaseTime+dt
    if s.phase=='prepare' and c.wait_for_range and c.in_reach==false then s.rangeWait=(s.rangeWait or 0)+dt end
    s.resourceObserved=s.resourceObserved or (s.attempted and c.resource_changed) or false
    local animated=c.animation_active
    if animated==nil then animated=c.busy or false end
    if c.dead then return finish(s,'player_down') end
    if s.kind=='wait' then
        s.released=true;s.quiet=s.elapsed
        if c.target_down then return finish(s,'target_down') end
        if c.target_lost then return finish(s,'target_lost') end
        if s.elapsed>=s.waitDuration then return finish(s,'completed') end
        return {attack=false}
    end
    if s.elapsed-(s.rangeWait or 0)>=6 then return finish(s,'step_limit') end
    if not c.can_move then return finish(s,'cannot_act') end
    if c.target_down then
        s.targetDown=true
        if not s.attempted then return finish(s,'target_down') end
        if s.phase~='recover' then s.phase='recover';s.phaseTime=0;return {attack=false} end
    end
    if c.target_lost and s.phase~='recover' then return finish(s,'target_lost') end
    if s.phase=='prepare' then
        local stance=s.kind=='strike' and 'weapon' or 'spell'
        if c.busy or c.recovering then s.quiet=0;s.readyFrames=0;return {attack=false} end
        if c.stance~=stance then
            s.quiet=0;s.readyFrames=0
            if not s.toggled then
                s.toggled=true
                return {attack=false,trigger=s.kind=='strike' and 'ToggleWeapon' or 'ToggleSpell'}
            end
            return {attack=false}
        end
        s.quiet=s.quiet+dt
        s.readyFrames=s.readyFrames+1
        if s.quiet<s.requiredQuiet or s.readyFrames<s.requiredReadyFrames then return {attack=false} end
        if c.unavailable_reason then return finish(s,c.unavailable_reason) end
        if c.in_reach==false then
            if c.wait_for_range then return {attack=false} end
            return finish(s,'out_of_reach')
        end
        if c.aligned==false then return {attack=false} end
        s.phase='hold';s.phaseTime=0;s.holdFrames=0;s.attempted=true;s.quiet=0
        return {attack=true}
    elseif s.phase=='hold' then
        s.holdFrames=s.holdFrames+1
        s.animationObserved=s.animationObserved or animated
        -- Keep the button held throughout a melee windup; small aim changes must not split it into several attacks.
        local duration=s.kind=='strike' and s.charge or .12
        if s.phaseTime>=duration and s.holdFrames>=2 then
            s.phase='recover';s.phaseTime=0
            return {attack=false}
        end
        return {attack=true}
    elseif s.phase=='recover' then
        s.released=true -- at least one simulation frame has consumed the released input
        s.animationObserved=s.animationObserved or animated
        if c.busy then s.quiet=0 else s.quiet=s.quiet+dt end
        if s.quiet>=.25 and s.phaseTime>=.35 then
            if s.targetDown then return finish(s,'target_down') end
            if c.resource_required and not s.resourceObserved then
                return finish(s,s.animationObserved and (s.kind=='strike' and 'shot_not_confirmed' or 'cast_not_confirmed') or 'action_not_started')
            end
            if s.animationObserved or s.resourceObserved then return finish(s,'completed') end
            return finish(s,'action_not_started')
        end
        return {attack=false}
    end
end
function M.report(s)
    return {elapsed=s.elapsed,reason=s.reason or 'interrupted',attempted=s.attempted,resource_observed=s.resourceObserved or false,
        released=s.released,animation_observed=s.animationObserved,
        animation_complete=s.released and s.quiet>=.25 and s.animationObserved,
        settled=s.released and s.quiet>=.25,
        outcome=s.reason=='completed' and (s.kind=='wait' and 'wait_completed' or 'use_completed') or s.reason=='target_down' and 'target_down'
            or not s.attempted and 'not_attempted' or 'interrupted'}
end
return M
