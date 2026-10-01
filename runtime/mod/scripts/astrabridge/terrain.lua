-- Bounded local navigation assistance. No object enumeration, hidden actor names,
-- world coordinates or unexplored routes are serialized.
local nearby=require('openmw.nearby')
local types=require('openmw.types')
local self=require('openmw.self')
local camera=require('openmw.camera')
local core=require('openmw.core')
local util=require('openmw.util')
local P=require('scripts.astrabridge.protocol')
local Space=require('scripts.astrabridge.space')
local Mobility=require('scripts.astrabridge.mobility')
local M={radius=6,units=70}
local cache,targets,marks,markOrder,serial,epoch=nil,{}, {},{},0,'test'
local function round(n)return math.floor(n*100+.5)/100 end
local function horizontal(v)return math.sqrt(v.x*v.x+v.y*v.y)end
local function angle(v)return (v+math.pi)%(2*math.pi)-math.pi end
local function options()
    return {agentBounds=types.Actor.getPathfindingAgentBounds(self),includeFlags=Mobility.flags(nearby.NAVIGATOR_FLAGS)}
end
local function kind(obj)
    if obj and types.Actor.objectIsInstance(obj) then return 'actor' end
    if obj and types.Door and types.Door.objectIsInstance(obj) then return 'door' end
    return 'geometry'
end
-- Three short body-width rays; unlike a sphere cast these can ignore the player.
function M.contact(from,to,centerOnly)
    local bounds=types.Actor.getPathfindingAgentBounds(self).halfExtents
    local height=bounds.z*2
    local d=to-from
    local len=horizontal(d)
    if len<.01 then return nil end
    local side=util.vector3(d.y/len,-d.x/len,0)*math.max(bounds.x,bounds.y)*.8
    local best
    local shifts=centerOnly and {util.vector3(0,0,0)} or {side,side*-1,util.vector3(0,0,0)}
    for _,shift in ipairs(shifts) do
        local up=util.vector3(0,0,height*.62)
        local a,b=from+up+shift,to+up+shift
        local ignored={self.object}
        local hit
        for attempt=1,5 do
            hit=nearby.castRay(a,b,{ignore=#ignored==1 and self.object or ignored})
            -- Corpses remain raycast targets for looting after the engine stops
            -- colliding with them. Ignore them for walking, while still probing
            -- the wall or living actor behind. Stock physics handles a death
            -- animation whose body has not yet become passable.
            local obj=hit.hitObject
            if not (hit.hit and obj and types.Actor.objectIsInstance(obj) and types.Actor.isDead(obj)) then break end
            if attempt<5 then ignored[#ignored+1]=obj end
        end
        if hit.hit and hit.hitPos and (not best or (hit.hitPos-a):length()<best.distance) then
            best={kind=kind(hit.hitObject),distance=(hit.hitPos-a):length()}
        end
    end
    return best
end
-- Validate a short physical walking corridor where a navmesh seam may be
-- missing. Sample actual floor support, including stair treads, and the body
-- envelope. This is local collision sensing, never a map or object search.
function M.walkLine(from,to)
    local delta=to-from
    local length=horizontal(delta)
    if length>420 or math.abs(delta.z)>length*1.1+20 then return nil end
    local steps=math.max(1,math.ceil(length/20))
    local path={from}
    local previous=from
    for i=1,steps do
        local target=from+delta*(i/steps)
        local hit=nearby.castRay(target+util.vector3(0,0,35),target-util.vector3(0,0,45),{ignore=self.object})
        if not hit.hit or not hit.hitPos or not hit.hitNormal or hit.hitNormal.z<.55
            or hit.hitObject and types.Actor.objectIsInstance(hit.hitObject) then return nil end
        local point=Mobility.surface(hit.hitPos)
        if math.abs(point.z-previous.z)>35 or M.contact(previous,point) then return nil end
        path[#path+1]=point;previous=point
    end
    if math.abs(previous.z-to.z)>25 then return nil end
    return path
end
-- Walk straight along the current floor. Stepwise sampling preserves ramps/stairs
-- and prevents selecting a point on a different floor merely because XY matches.
function M.probe(yaw,meters)
    local opts=options()
    local start=self.position
    local point=start
    local dir=util.vector3(math.sin(yaw),math.cos(yaw),0)
    local steps=math.ceil(meters/.75)
    local step=meters*M.units/steps
    local obstacle
    local profile={start}
    for _=1,steps do
        local nextPoint=Mobility.surface(nearby.castNavigationRay(point,point+dir*step,opts))
        if not nextPoint then
            local hit=M.contact(point,point+dir*step)
            return {point=point,distance=horizontal(point-start),vertical=point.z-start.z,obstacle=hit and hit.kind or 'navmesh_unavailable',profile=profile}
        end
        local d=nextPoint-point
        if horizontal(d)<step*.55 or math.abs(d.z)>step*1.1+20 then obstacle='nav_boundary';break end
        -- A raycast may snap within a polygon; reject discontinuous sideways/floor jumps.
        if math.abs(d.x*dir.y-d.y*dir.x)>25 then obstacle='nav_boundary';break end
        local hit=M.contact(point,nextPoint)
        if hit then obstacle=hit.kind;break end
        point=nextPoint;profile[#profile+1]=point
        if horizontal(d)<step*.9 then obstacle='nav_boundary';break end
    end
    return {point=point,distance=horizontal(point-start),vertical=point.z-start.z,obstacle=obstacle,profile=profile}
end
function M.reset(namespace)
    cache,targets,marks,markOrder,serial,epoch=nil,{}, {},{},0,namespace
end
function M.invalidate()cache=nil;targets={}end
local labels={'front','front_right','right','back_right','back','back_left','left','front_left'}
function M.observe(force)
    if Mobility.has('Levitate') then return {supported=false,reason='flight_requires_fly'} end
    if types.Actor.isSwimming and types.Actor.isSwimming(self) then return {supported=false,reason='swimming_requires_manual_control'} end
    if not nearby.castNavigationRay or not nearby.castRay then return {supported=false} end
    local pos,yaw,time,cell=self.position,camera.getYaw(),core.getSimulationTime(),Space.key(self.cell)
    local waterWalking=Mobility.has('WaterWalking')
    if not force and cache and cache.waterWalking==waterWalking and cache.cell==cell and (cache.position-pos):length()<14
        and math.abs(angle(cache.yaw-yaw))<math.rad(4) and time-cache.time<.6 then return cache.public end
    targets={};serial=serial+1
    local rays,passages=P.array(),P.array()
    local private={}
    for i=0,23 do
        local bearing=i*15
        if bearing>180 then bearing=bearing-360 end
        local ok,p=pcall(M.probe,yaw+math.rad(bearing),M.radius)
        if not ok then return {supported=false,reason='survey_unavailable'} end
        local distance=p.distance/M.units
        local row={bearing_deg=bearing,clear_m=round(distance),height_change_m=round(p.vertical/M.units),
            status=p.obstacle or 'range_limit'}
        rays[#rays+1]=row;private[i+1]=p
    end
    -- One useful waypoint per 45-degree sector, chosen by clearance. Neighbouring
    -- sectors with almost identical endpoints are collapsed instead of spamming refs.
    for sector=0,7 do
        local best
        for _,offset in ipairs({0,-1,1}) do
            local index=(sector*3+offset)%24+1
            if not best or rays[index].clear_m>rays[best].clear_m+.25 then best=index end
        end
        local p,row=private[best],rays[best]
        -- Leave room to turn at an obstruction; a navmesh boundary is not a good
        -- resting position. The clearance ray remains available separately.
        local point=p.obstacle and #p.profile>2 and p.profile[#p.profile-1] or p.point
        local distance=horizontal(point-pos)/M.units
        local duplicate=false
        for _,other in pairs(targets) do if (point-other.point):length()<90 then duplicate=true end end
        if distance>=1 and not duplicate then
            local ref='passage_'..epoch..'_'..serial..'_'..sector
            targets[ref]={point=point,origin=pos,cell=cell,time=time}
            local height=(point.z-pos.z)/M.units
            local slope=height>.45 and 'up' or height<-.45 and 'down' or 'level'
            passages[#passages+1]={ref=ref,direction=labels[sector+1],bearing_deg=row.bearing_deg,
                distance_m=round(distance),clear_m=row.clear_m,height_change_m=round(height),slope=slope,status=row.status}
        end
    end
    local public={supported=true,radius_m=M.radius,source='local_navmesh_and_collision',
        rays=rays,passages=passages,not_a_full_map=true}
    cache={public=public,position=pos,yaw=yaw,time=time,cell=cell,waterWalking=waterWalking}
    return public
end
function M.resolve(ref)
    local mark=marks[ref]
    if mark and mark.cell==Space.key(self.cell) and (mark.point-self.position):length()<7000 then return mark.point end
    local goal=targets[ref]
    if goal and goal.cell==Space.key(self.cell) and (goal.origin-self.position):length()<35
        and core.getSimulationTime()-goal.time<3 then return goal.point end
end
function M.route(ref)
    if M.resolve(ref) then return marks[ref] and marks[ref].route end
end
function M.mark(offset,route)
    local point=self.position
    if offset then
        -- Controller-only restoration of this player's recorded path after
        -- loading its matching checkpoint. Public mark accepts no coordinates.
        assert(type(offset)=='table' and #offset==3)
        local d=util.vector3(P.number(offset[1],-100,100,0),P.number(offset[2],-100,100,0),P.number(offset[3],-100,100,0))
        assert(d:length()<100)
        point=point+d*M.units
    end
    serial=serial+1
    local ref='waypoint_'..epoch..'_'..serial
    marks[ref]={point=point,cell=Space.key(self.cell)}
    if route then
        assert(type(route)=='table' and #route>0 and #route<=800)
        local points={}
        for i,p in ipairs(route) do
            assert(type(p)=='table' and #p==3)
            local d=util.vector3(P.number(p[1],-100,100),P.number(p[2],-100,100),P.number(p[3],-100,100))
            assert(d:length()<100)
            points[i]=self.position+d*M.units
        end
        assert((points[1]-self.position):length()<10 and (points[#points]-point):length()<3)
        marks[ref].route=points
    end
    markOrder[#markOrder+1]=ref
    if #markOrder>64 then marks[table.remove(markOrder,1)]=nil end
    return ref
end
return M
