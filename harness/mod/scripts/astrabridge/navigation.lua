-- Private motor assistance using the same navigation mesh as engine NPCs.
-- Only aggregate progress is exported. No path points or hidden moving-target positions.
local nearby=require('openmw.nearby')
local self=require('openmw.self')
local types=require('openmw.types')
local util=require('openmw.util')
local Space=require('scripts.astrabridge.space')
local Mobility=require('scripts.astrabridge.mobility')
local M={}
local function horizontal(v)return math.sqrt(v.x*v.x+v.y*v.y)end
local function destination(g)
    if g.groundPoint then return Mobility.surface(g.groundPoint) end
    if types.Actor.objectIsInstance(g.obj) then return g.obj.position end
    return util.vector3(g.center.x,g.center.y,g.center.z-g.half.z)
end
local function useRecorded(n,reason)
    if not n.recordedPath then return false end
    n.recorded=true;n.path=n.recordedPath;n.index=1;n.endpointMismatch=nil
    n.status='recorded';n.pathStatus='recorded';n.fallbackReason=reason
    return true
end
local function plan(n,g)
    if n.recorded then return end
    n.waterWalking=Mobility.has('WaterWalking')
    if g then n.lastGoal=g;n.goal=destination(g) end
    n.replans=n.replans+1
    local flags=nearby.NAVIGATOR_FLAGS
    local ok,status,path=pcall(nearby.findPath,self.position,n.goal,{
        agentBounds=types.Actor.getPathfindingAgentBounds(self),
        includeFlags=Mobility.flags(flags)+flags.UsePathgrid,
        destinationTolerance=n.tolerance,
    })
    n.path=nil;n.index=1;n.localPath=nil;n.endpointMismatch=nil
    if not ok then n.status='unavailable';useRecorded(n,'navigation_unavailable');return end
    if (status==nearby.FIND_PATH_STATUS.Success or status==nearby.FIND_PATH_STATUS.PartialPath) and #path>0 then
        local surfacePath={}
        for i,p in ipairs(path) do surfacePath[i]=Mobility.surface(p) end
        path=surfacePath
        n.path=path;n.status=status==nearby.FIND_PATH_STATUS.Success and 'planned' or 'partial'
        if n.lastGoal and n.lastGoal.groundPoint and (path[#path]-n.goal):length()>25 then n.status='partial' end
        -- A partial route may end in the room underneath the destination. It
        -- is not useful progress towards a point on the other floor.
        n.endpointMismatch=math.abs(path[#path].z-n.goal.z)>70
    else n.status='no_path' end
    n.pathStatus=n.status
    if n.recordedPath and (not n.path or n.status=='partial' or n.endpointMismatch) then
        useRecorded(n,'incomplete_navmesh')
    end
    if not n.recorded and n.lastGoal and n.lastGoal.groundPoint
        and (not n.path or n.status=='partial' or n.endpointMismatch) then
        local terrain=require('scripts.astrabridge.terrain')
        local direct=terrain.walkLine and terrain.walkLine(self.position,n.goal)
        if direct then
            n.path=direct;n.index=1;n.endpointMismatch=nil;n.status='local';n.pathStatus='local';n.localPath=true
        end
    end
end
function M.new(g)
    local n={status='unavailable',replans=0,sincePlan=0,lastGoal=g,
        tolerance=g.groundPoint and 16 or 120,recoveryCount=0,attempts=0,
        movingTarget=g.obj and types.Actor.objectIsInstance(g.obj) or false,cell=self.cell and Space.key(self.cell)}
    n.recordedPath=g.recordedPath
    if nearby.findPath and types.Actor.getPathfindingAgentBounds then plan(n,g)
    elseif n.recordedPath then n.goal=destination(g);useRecorded(n,'navigation_unavailable') end
    -- Native navigation remains the first choice. Its smooth path can cross
    -- a rotating door leaf, however: test the actual body corridor, not just
    -- the success status. Use the player's recorded route when available.
    if n.path and not n.recorded and n.recordedPath then
        local previous=self.position
        for _,point in ipairs(n.path) do
            local hit=require('scripts.astrabridge.terrain').contact(previous,point)
            if hit then useRecorded(n,hit.kind=='actor' and 'navmesh_actor' or 'navmesh_obstructed');break end
            previous=point
        end
    end
    return n
end
function M.step(n,g,dt)
    local previous=n.previousPosition or self.position
    n.previousPosition=self.position
    n.lastMovement=horizontal(self.position-previous)
    if n.waitRemaining then
        n.waitRemaining=n.waitRemaining-dt
        if n.waitRemaining>0 then n.status='waiting';return self.position end
        n.waitRemaining=nil;n.status=n.pathStatus or 'planned'
    end
    if n.detour then
        if horizontal(n.detour-self.position)>24 then n.status='detour';return n.detour end
        if n.detourJoin then n.detour=n.detourJoin;n.detourJoin=nil;return n.detour end
        n.detour=nil
        if n.rejoinIndex then n.index=n.rejoinIndex;n.rejoinIndex=nil;n.status=n.pathStatus
        else plan(n,nil) end
    end
    n.sincePlan=n.sincePlan+dt
    if g then
        n.lastGoal=g
        if n.goal and n.sincePlan>=(n.replanInterval or 1) and (destination(g)-n.goal):length()>35 then
            plan(n,g);n.sincePlan=0
        end
    end
    if not n.path then return nil end
    if n.endpointMismatch then n.status='endpoint_mismatch';return nil end
    while n.index<=#n.path do
        local d=n.path[n.index]-self.position
        -- Never skip a waypoint on a different floor merely because its XY matches.
        local radius=n.recorded and 10 or 24
        if n.index==#n.path and n.goal then
            local gap=horizontal(n.path[n.index]-n.goal)
            local tolerance=n.arrivalTolerance or 25
            if gap<tolerance-1 then radius=math.max(1,math.min(radius,tolerance-gap-1)) end
        end
        local reached=horizontal(d)<radius and math.abs(d.z)<35
        if n.index==#n.path and horizontal(d)<radius and math.abs(d.z)>=35 then
            -- There is no horizontal direction left to follow. Do not spin on
            -- an endpoint below/above the feet until the command budget expires.
            n.status='height_mismatch';return nil
        end
        if not reached and n.index<#n.path then
            -- At low FPS a physics step can cross a short waypoint's entire
            -- acceptance region. Use the swept segment for intermediate points,
            -- so following the path does not turn back to a point already passed.
            local movement=self.position-previous
            local length2=movement.x*movement.x+movement.y*movement.y
            if length2>0 then
                local offset=n.path[n.index]-previous
                local t=math.max(0,math.min(1,(offset.x*movement.x+offset.y*movement.y)/length2))
                local crossed=n.path[n.index]-(previous+movement*t)
                reached=horizontal(crossed)<24 and math.abs(crossed.z)<35
            end
        end
        if reached then n.index=n.index+1 else break end
    end
    if n.index>#n.path then n.status='path_end';return nil end
    -- Look ahead only along a nearly straight piece of the existing route.
    -- The body-width collision test prevents cutting a doorway corner or an
    -- opened door leaf. Recorded routes retain their original floor profile.
    if n.recorded then
        local terrain=require('scripts.astrabridge.terrain')
        local start=self.position
        for j=n.index+1,math.min(#n.path,n.index+12) do
            local d=n.path[j]-start
            local len2=d.x*d.x+d.y*d.y
            if len2>140*140 or len2<1 then break end
            local safe=true
            for k=n.index,j-1 do
                local v=n.path[k]-start
                local t=math.max(0,math.min(1,(v.x*d.x+v.y*d.y)/len2))
                local error=v-d*t
                if horizontal(error)>6 or math.abs(error.z)>15 then safe=false;break end
            end
            if not safe or terrain.contact(start,n.path[j]) then break end
            n.index=j
        end
    end
    return n.path[n.index]
end
function M.begin(n)n.attempts=0;n.blockedBy=nil end
function M.reached(n)
    local d=n.goal-self.position
    return horizontal(d)<(n.arrivalTolerance or 25) and math.abs(d.z)<35
end
function M.canFinish(n)
    if (n.arrivalTolerance or 25)<=25 or horizontal(n.goal-self.position)<25 then return true end
    -- A loose passage tolerance must not claim arrival through a thin wall or
    -- on the other side of a corner. The nearby goal must be directly reachable.
    local ok,clear=pcall(function()
        local hit=nearby.castNavigationRay(self.position,n.goal,{agentBounds=types.Actor.getPathfindingAgentBounds(self),
            includeFlags=Mobility.flags(nearby.NAVIGATOR_FLAGS)})
        hit=Mobility.surface(hit)
        return hit and horizontal(hit-n.goal)<24 and math.abs(hit.z-n.goal.z)<35
            and not require('scripts.astrabridge.terrain').contact(self.position,n.goal)
    end)
    return ok and clear or false
end
function M.clearance(n,point)
    -- This guard uses physical contact only, never an enumeration of actors.
    local ok,hit=pcall(function()
        local d=point-self.position
        local length=d:length()
        if length<1 then return nil end
        return require('scripts.astrabridge.terrain').contact(self.position,self.position+d*math.min(1,65/length))
    end)
    if not ok then n.blockedBy='probe_unavailable';return 0 end
    if hit then n.blockedBy=hit.kind;return 0 end
    n.blockedBy=nil;return 1
end
function M.recover(n,yaw)
    local limit=n.blockedBy=='actor' and 4 or 2
    if (n.attempts or 0)>=limit then return false end
    n.attempts=(n.attempts or 0)+1;n.recoveryCount=(n.recoveryCount or 0)+1
    if n.blockedBy=='actor' then
        if n.attempts==1 then n.waitRemaining=.7;return true end
        -- The actor can move during our finite turn. Drop a stale sidestep and
        -- recompute from the actual pose, within the same bounded action.
        n.detour=nil;n.detourJoin=nil;n.rejoinIndex=nil
        -- Test both legs of a short sidestep to a point farther along the
        -- existing path. Never choose the final goal across a wall/floor as
        -- the detour's score. Actors may have moved since the route was saved.
        local terrain=require('scripts.astrabridge.terrain')
        local best,score
        local joins={}
        local previous=self.position
        local travelled=0
        for j=n.index,math.min(#n.path,n.index+16) do
            local delta=n.path[j]-previous
            local length=delta:length()
            local steps=math.max(1,math.ceil(length/35))
            for i=1,math.min(steps,12) do
                local distance=travelled+length*i/steps
                if distance>210 then break end
                if distance>65 then joins[#joins+1]={point=previous+delta*(i/steps),index=j} end
            end
            travelled=travelled+length
            if travelled>210 then break end
            previous=n.path[j]
        end
        local forward=n.path[n.index]-self.position
        local routeYaw=math.atan2(forward.x,forward.y)
        for _,offset in ipairs({90,-90,60,-60,120,-120}) do
            local ok,p=pcall(terrain.probe,routeYaw+math.rad(offset),1.1)
            if ok and p.distance>45 and math.abs(p.vertical)<25 and not p.obstacle then
                for _,join in ipairs(joins) do
                    local goal=join.point
                    local d=goal-self.position
                    if horizontal(d)>65 and math.abs(goal.z-p.point.z)<25
                        and terrain.walkLine(p.point,goal) then
                        local cost=(p.point-self.position):length()+(goal-p.point):length()
                        if not score or cost<score then best={point=p.point,join=goal,index=join.index};score=cost end
                    end
                end
            end
        end
        if best then n.detour=best.point;n.detourJoin=best.join;n.rejoinIndex=best.index;n.status='detour';return true end
        return false
    end
    if n.recorded then return false end
    if n.attempts==1 then
        -- Freeze the last known endpoint, especially if a moving NPC is now hidden.
        plan(n,nil)
        return n.path~=nil
    end
    local best,score
    for _,offset in ipairs({60,-60,90,-90}) do
        local ok,p=pcall(function()return require('scripts.astrabridge.terrain').probe(yaw+math.rad(offset),1.1)end)
        if ok and p.distance>55 and math.abs(p.vertical)<45 and not p.obstacle then
            local value=(p.point-n.goal):length()
            if not score or value<score then best,score=p.point,value end
        end
    end
    if best then n.detour=best;n.status='detour';return true end
    return false
end
function M.report(n)
    local out={status=n.status,replans=n.replans,recovery_count=n.recoveryCount or 0,blocked_by=n.blockedBy,
        source=n.recorded and 'recorded_trail' or n.localPath and 'local_collision' or 'navmesh',reason=n.fallbackReason}
    if n.goal then
        out.goal_distance_m=math.floor(horizontal(n.goal-self.position)/70*100+.5)/100
        out.goal_height_change_m=math.floor((n.goal.z-self.position.z)/70*100+.5)/100
    end
    if n.arrivalTolerance then out.arrival_tolerance_m=n.arrivalTolerance/70 end
    if n.path then
        out.path_endpoint_gap_m=math.floor((n.path[#n.path]-n.goal):length()/70*100+.5)/100
        local length=0;local previous=self.position
        for i=n.index,#n.path do length=length+(n.path[i]-previous):length();previous=n.path[i] end
        out.remaining_m=math.floor(length/70*100+.5)/100
    end
    return out
end
-- Lua input reaches physics on a later frame. Slow down before short segments,
-- especially on the low-FPS software renderer, instead of overshooting and turning back.
function M.moveFraction(waypoint,dt,run,n)
    local getter=run and types.Actor.getRunSpeed or types.Actor.getWalkSpeed
    local speed=getter and getter(self) or 200
    local remaining=horizontal(waypoint-self.position)
    local delay=n and n.inputDelayFrames or 2
    local queued=(n and n.lastMovement or 0)*delay
    local horizon=math.max(dt,delay==0 and .2 or .02)*math.max(1,delay)
    return math.min(1,math.max(0,remaining-queued)/math.max(24,speed*horizon))
end
return M
