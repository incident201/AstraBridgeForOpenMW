-- V2 permission boundary: world coordinates stay here; only visible names,
-- screen-space targets and relative measurements leave the adapter.
local camera = require('openmw.camera')
local nearby = require('openmw.nearby')
local types = require('openmw.types')
local self = require('openmw.self')
local core = require('openmw.core')
local util = require('openmw.util')
local ui = require('openmw.ui')
local P = require('scripts.astrabridge.protocol')
local Space=require('scripts.astrabridge.space')
local hasAnimation,animation=pcall(require,'openmw.animation')
local M = {unitsPerMeter=70}
local handles, ids, seen, preferred, serial, epoch = {}, {}, {}, {}, 0, 0
local groundTargets,groundSerial={},0
local preferredPoints={}
local function round(x) return math.floor(x*100+.5)/100 end
function M.angle(x) return (x+math.pi)%(2*math.pi)-math.pi end
function M.reset(e) handles,ids,seen,preferred,serial,epoch={},{},{},{},0,e;groundTargets={};groundSerial=0;preferredPoints={} end
function M.orientation()
    local s=ui.screenSize()
    local vf=camera.getFieldOfView()
    local mode
    if camera.MODE and camera.getMode then
        for name,value in pairs(camera.MODE) do if value==camera.getMode() then mode=name end end
    end
    return {heading_deg=round(math.deg(camera.getYaw())%360),pitch_deg=round(math.deg(camera.getPitch())),view_mode=mode,
        horizontal_fov_deg=round(math.deg(2*math.atan(math.tan(vf/2)*s.x/s.y)))}
end
function M.fov(degrees)
    local s=ui.screenSize()
    camera.setFieldOfView(2*math.atan(math.tan(math.rad(degrees)/2)*s.y/s.x))
end
local function geometry(obj,offscreen)
    if not obj:isValid() or not obj.enabled then return nil end
    if not obj.cell then return nil end
    if Space.key(obj.cell)~=Space.key(self.cell) then return nil end
    local origin=camera.getPosition()
    local box=obj:getBoundingBox()
    local center,half=box.center,box.halfSize
    local delta=center-origin
    if delta:length()>2800 then return nil end
    local forward=camera.viewportToWorldVector(util.vector2(.5,.5))
    if not offscreen and delta:dot(forward)<=0 then return nil end
    if types.Actor.objectIsInstance(obj) then
        local effects=types.Actor.activeEffects(obj)
        local effect=effects:getEffect('invisibility')
        if effect and effect.magnitude>0 then return nil end
        local concealment=effects:getEffect('chameleon')
        if concealment and concealment.magnitude>=100 then return nil end
    end
    local size=ui.screenSize()
    local minX,minY,maxX,maxY=size.x,size.y,0,0
    for _,v in ipairs(box.vertices) do
        if (v-origin):dot(forward)>0 then
            local p=camera.worldToViewportVector(v)
            minX=math.min(minX,p.x);minY=math.min(minY,p.y)
            maxX=math.max(maxX,p.x);maxY=math.max(maxY,p.y)
        end
    end
    if not offscreen and (maxX<0 or maxY<0 or minX>size.x or minY>size.y) then return nil end
    return {obj=obj,origin=origin,center=center,half=half,distance=delta:length(),
        rect={math.max(0,minX),math.max(0,minY),math.min(size.x,maxX)-math.max(0,minX),math.min(size.y,maxY)-math.max(0,minY)}}
end
local offsets={{0,0,0},{0,0,.65},{0,0,-.5},{.6,0,0},{-.6,0,0},{0,.6,0},{0,-.6,0}}
local function visible(g,budget,offscreen)
    if not g then return nil end
    local size=ui.screenSize()
    local picked=preferredPoints[g.obj.id]
    if picked then
        local screen=camera.worldToViewportVector(picked)
        if offscreen or screen.x>=0 and screen.y>=0 and screen.x<size.x and screen.y<size.y then
            local ray=nearby.castRenderingRay(g.origin,picked+(picked-g.origin):normalize()*4,{ignore=self.object})
            if ray.hitObject==g.obj then
                g.point=ray.hitPos;g.screen={round(screen.x),round(screen.y)};g.distance=(ray.hitPos-g.origin):length()
                return g
            end
        end
    end
    local order={}
    local key=g.obj.id
    if preferred[key] then order[#order+1]=preferred[key] end
    for index=1,#offsets do if index~=preferred[key] then order[#order+1]=index end end
    for _,index in ipairs(order) do
        local o=offsets[index]
        if budget then if budget.left<=0 then return nil end;budget.left=budget.left-1 end
        local target=g.center+util.vector3(g.half.x*o[1],g.half.y*o[2],g.half.z*o[3])
        local screen=camera.worldToViewportVector(target)
        if offscreen or (screen.x>=0 and screen.x<size.x and screen.y>=0 and screen.y<size.y) then
            -- Some door meshes are almost planar. Ending exactly on their bounds
            -- can miss the triangle numerically; extend the same ray slightly.
            -- First-hit identity still prevents looking through an occluder.
            local direction=target-g.origin
            local ray=nearby.castRenderingRay(g.origin,target+direction:normalize()*4,{ignore=self.object})
            if ray.hitObject and ray.hitObject==g.obj then
                preferred[key]=index
                local p=camera.worldToViewportVector(ray.hitPos)
                g.point=ray.hitPos;g.screen={round(p.x),round(p.y)}
                g.distance=(ray.hitPos-g.origin):length()
                return g
            end
        end
    end
end
function M.resolve(ref,remembered)
    local obj=handles[ref]
    if not obj then return nil end
    local ok,g=pcall(function() return visible(geometry(obj)) end)
    if ok and g then seen[ref]=core.getSimulationTime();return g end
    local memorySeconds=types.Actor.objectIsInstance(obj) and 5 or 60
    if remembered and core.getSimulationTime()-(seen[ref] or -100)<memorySeconds then
        local good,result=pcall(function() return visible(geometry(obj,true),nil,true) end)
        if good then return result end
    end
end
function M.lookAngles(g)
    local v=g.point-camera.getPosition()
    return math.atan2(v.x,v.y),math.atan2(-v.z,math.sqrt(v.x*v.x+v.y*v.y))
end
function M.track(ref)
    local obj=handles[ref]
    if not obj or not types.Actor.objectIsInstance(obj) then return nil end
    -- Animated visual bounds and rendering ray geometry can be one frame apart.
    -- Once an actor is selected from sight, use its physical shape for motor LOS.
    -- World/door collisions still occlude it; no new targets are discovered here.
    local ok,g=pcall(function()
        local v=geometry(obj,true)
        if not v then return nil end
        for _,z in ipairs({0,.65,-.5}) do
            local point=v.center+util.vector3(0,0,v.half.z*z)
            local ray=nearby.castRay(v.origin,point,{ignore=self.object})
            if ray.hitObject==obj then
                v.point=point;v.distance=(point-v.origin):length()
                seen[ref]=core.getSimulationTime()
                return v
            end
        end
    end)
    if ok and g then return g end
    return M.resolve(ref,true)
end
function M.lootReady(g)
    if not g or not types.Actor.objectIsInstance(g.obj) or not types.Actor.isDead(g.obj) then return nil end
    if not hasAnimation or not animation.getActiveGroup then return nil end
    local ok,ready=pcall(function()
        for _,part in ipairs({animation.BONE_GROUP.LowerBody,animation.BONE_GROUP.Torso}) do
            local group=animation.getActiveGroup(g.obj,part)
            if group and (group:match('^death') or group:match('^swimdeath')) and animation.isPlaying(g.obj,group) then return false end
        end
        return true
    end)
    if ok then return ready end
end
function M.combatAligned(g)
    local yaw,pitch=M.lookAngles(g)
    return math.abs(M.angle(yaw-camera.getYaw()))<math.rad(18)
        and math.abs(pitch-camera.getPitch())<math.rad(18)
end
function M.reach(g,margin)
    return g.distance<=core.getGMST('iMaxActivateDist')*(margin or .94)
end
function M.crosshair(g)
    local from=camera.getPosition()
    local dir=camera.viewportToWorldVector(util.vector2(.5,.5)):normalize()
    local ray=nearby.castRenderingRay(from,from+dir*(core.getGMST('iMaxActivateDist')+10),{ignore=self.object})
    return ray.hitObject and ray.hitObject==g.obj
end
function M.aimedAt(g)
    local from=camera.getPosition()
    local dir=camera.viewportToWorldVector(util.vector2(.5,.5)):normalize()
    local ray=nearby.castRenderingRay(from,from+dir*(g.distance+g.half:length()*2+8),{ignore=self.object})
    return ray.hitObject and ray.hitObject==g.obj
end
local function publicObject(g,v)
            local rec=g.obj.type.record(g.obj)
            if rec and rec.name and rec.name~='' then
                local key=g.obj.id -- private lookup; never serialize or hash this into a public ref
                local ref=ids[key]
                if not ref then serial=serial+1;ref='visible_'..epoch..'_'..serial;ids[key]=ref end
                handles[ref]=g.obj
                seen[ref]=core.getSimulationTime()
                local yaw=M.lookAngles(g)
                local row={ref=ref,name=rec.name,kind=g.kind,rect=P.array(),aim_point=P.array(v.screen),
                    distance_m=round(v.distance/M.unitsPerMeter),bearing_deg=round(math.deg(M.angle(yaw-camera.getYaw()))),
                    in_reach=M.reach(g),actions=P.array({'focus','approach','interact'})}
                if g.kind=='actor' then
                    row.status=types.Actor.isDead(g.obj) and 'down' or 'active'
                    if row.status=='down' then row.loot_ready=M.lootReady(g) end
                    if ui._astraTargetReach then
                        for k,value in pairs(ui._astraTargetReach(g.obj)) do row[k]=value end
                    end
                elseif (g.kind=='door' or g.kind=='container') and ui._astraDoorDescription then
                    row.description=ui._astraDoorDescription(g.obj)
                end
                for _,n in ipairs(g.rect) do row.rect[#row.rect+1]=round(n) end
                return row
            end
end
function M.pick(x,y,radius)
    local size=ui.screenSize()
    if x<0 or y<0 or x>=size.x or y>=size.y then return {reason='invalid_arguments'} end
    local origin=camera.getPosition();local rows=P.array();local found={}
    local offsets=radius>0 and {-1,-.75,-.5,-.25,0,.25,.5,.75,1} or {0}
    for _,dx in ipairs(offsets) do for _,dy in ipairs(offsets) do
        local sx,sy=x+dx*radius,y+dy*radius
        if sx>=0 and sy>=0 and sx<size.x and sy<size.y then
            local direction=camera.viewportToWorldVector(util.vector2(sx/size.x,sy/size.y)):normalize()
            local ray=nearby.castRenderingRay(origin,origin+direction*2800,{ignore=self.object})
            local obj=ray.hitObject
            if obj and not found[obj.id] then
                local g=geometry(obj)
                if g then
                    for _,kind in ipairs({'Actor','Door','Container','Item','Activator'}) do
                        if types[kind] and types[kind].objectIsInstance(obj) then g.kind=kind:lower();break end
                    end
                    if g.kind then
                        g.point=ray.hitPos;g.screen={round(sx),round(sy)};g.distance=(g.point-origin):length()
                        preferredPoints[obj.id]=g.point
                        local row=publicObject(g,g)
                        if row then rows[#rows+1]=row;found[obj.id]=true end
                    end
                end
            end
        end
    end end
    return {objects=rows,reason=#rows>0 and 'visible_object_found' or 'no_interactable_object_at_pixels',scope='visible_pixels'}
end
function M.observe()
    local candidates={}
    for _,group in ipairs({{nearby.actors,'actor'},{nearby.doors,'door'},{nearby.containers,'container'},
        {nearby.items,'item'},{nearby.activators,'activator'}}) do
        for _,obj in ipairs(group[1]) do
            if obj~=self.object then
                local ok,g=pcall(geometry,obj)
                if ok and g then g.kind=group[2];candidates[#candidates+1]=g end
            end
        end
    end
    require('scripts.astrabridge.sampling').order(candidates)
    local budget={left=180}
    local result=P.array()
    for _,g in ipairs(candidates) do
        if #result>=28 or budget.left<=0 then break end
        local ok,v=pcall(visible,g,budget)
        if ok and v then
            local row=publicObject(g,v)
            if row then result[#result+1]=row end
        end
    end
    return {objects=result,sampling_limited=budget.left<=0 or #result>=28,orientation=M.orientation()}
end
function M.pose() return {position=self.position,yaw=camera.getYaw(),pitch=camera.getPitch(),cell=Space.key(self.cell)} end
function M.groundPoint(x,y)
    local size=ui.screenSize()
    if x<0 or y<0 or x>=size.x or y>=size.y then return nil end
    local from=camera.getPosition()
    local direction=camera.viewportToWorldVector(util.vector2(x/size.x,y/size.y))
    local ray=nearby.castRenderingRay(from,from+direction*2100,{ignore=self.object})
    local level=require('scripts.astrabridge.mobility').waterLevel()
    if level and from.z>level and direction.z<0 then
        local distance=(level-from.z)/direction.z
        -- The surface must be in front of any rendered wall/shore/object.
        if distance>0 and distance<=2100 and (not ray.hit or ray.hitPos and distance<=(ray.hitPos-from):length()+1) then
            return from+direction*distance
        end
    end
    if not ray.hit or not ray.hitPos or not ray.hitNormal or ray.hitNormal.z<.55 then return nil end
    if ray.hitObject and (types.Actor.objectIsInstance(ray.hitObject) or types.Item.objectIsInstance(ray.hitObject)) then return nil end
    return ray.hitPos
end
function M.report(start)
    local changed=Space.key(self.cell)~=start.cell
    local delta=changed and util.vector3(0,0,0) or self.position-start.position
    local yaw=start.yaw
    return {forward_m=round((delta.x*math.sin(yaw)+delta.y*math.cos(yaw))/M.unitsPerMeter),
        sideways_m=round((delta.x*math.cos(yaw)-delta.y*math.sin(yaw))/M.unitsPerMeter),
        moved_m=round(delta:length()/M.unitsPerMeter),vertical_m=round(delta.z/M.unitsPerMeter),turned_deg=round(math.deg(M.angle(camera.getYaw()-yaw))),
        pitch_changed_deg=round(math.deg(camera.getPitch()-start.pitch)),location_changed=changed}
end
function M.groundTargets()
    local result=P.array()
    groundTargets={};groundSerial=groundSerial+1
    if not nearby.findPath or not types.Actor.getPathfindingAgentBounds then return result end
    local size=ui.screenSize()
    local groups={}
    -- Only actual visible surfaces. No navmesh point is invented beyond the ray.
    for _,fy in ipairs({.45,.60,.75,.90,.97}) do
        for _,fx in ipairs({.1,.3,.5,.7,.9}) do
            local x,y=math.floor(size.x*fx),math.floor(size.y*fy)
            local point=M.groundPoint(x,y)
            if point then
                local d=point-self.position
                local distance=d:length()/M.unitsPerMeter
                if distance>=1 and distance<=30 then
                    local height=d.z/M.unitsPerMeter
                    local band=height< -1 and 1 or height>1 and 3 or 2
                    local side=math.min(3,math.floor(fx*3)+1)
                    local key=(band-1)*3+side
                    local entry={point=point,distance=distance,height=height,x=x,y=y,band=band,side=side}
                    if not groups[key] or distance>groups[key].distance then groups[key]=entry end
                end
            end
        end
    end
    local accepted={}
    for key=1,9 do
        local g=groups[key]
        if g then
            local N=require('scripts.astrabridge.navigation')
            local nav=N.new({groundPoint=g.point})
            local adjustment=0
            if nav.path and #nav.path>0 then
                local endpoint=nav.path[#nav.path]
                local gap=(endpoint-g.point):length()
                if gap>1 then
                    if gap>25 then nav.status='partial' end
                    -- The engine's destination tolerance includes actor bounds.
                    -- Suggest the reachable point only if it is close, on the
                    -- same floor, visibly projected, and not beyond a wall.
                    local ok,visiblePoint=pcall(function()
                        if gap>105 or math.abs(endpoint.z-g.point.z)>52.5 or (endpoint-self.position):length()>2100 then return nil end
                        -- Recast onto the physical tread. The navmesh is a
                        -- simplified surface and can lie below a stair by more
                        -- than our arrival tolerance; its Z is not a foot pose.
                        local floorRay=nearby.castRay(endpoint+util.vector3(0,0,70),endpoint-util.vector3(0,0,70),{ignore=self.object})
                        if not floorRay.hit or not floorRay.hitPos or not floorRay.hitNormal or floorRay.hitNormal.z<.55 then return nil end
                        if floorRay.hitObject and (types.Actor.objectIsInstance(floorRay.hitObject) or types.Item.objectIsInstance(floorRay.hitObject)) then return nil end
                        local candidate=floorRay.hitPos
                        if (candidate-g.point):length()>105 or math.abs(candidate.z-g.point.z)>52.5 then return nil end
                        local origin=camera.getPosition()
                        if (candidate-origin):dot(camera.viewportToWorldVector(util.vector2(.5,.5)))<=0 then return nil end
                        local screen=camera.worldToViewportVector(candidate)
                        local floor=M.groundPoint(screen.x,screen.y)
                        if not floor or (floor-candidate):length()>35 then return nil end
                        if require('scripts.astrabridge.terrain').contact(candidate,g.point,true) then return nil end
                        return {screen=screen,point=candidate}
                    end)
                    if ok and visiblePoint then
                        adjustment=(visiblePoint.point-g.point):length()/M.unitsPerMeter
                        g.point=visiblePoint.point;g.x=round(visiblePoint.screen.x);g.y=round(visiblePoint.screen.y)
                        local d=g.point-self.position;g.distance=d:length()/M.unitsPerMeter;g.height=d.z/M.unitsPerMeter
                        g.band=g.height< -1 and 1 or g.height>1 and 3 or 2
                        g.side=math.min(3,math.floor(g.x/size.x*3)+1)
                        nav.goal=g.point;nav.status='planned';nav.pathStatus='planned'
                    end
                end
            end
            local duplicate=false
            for _,point in ipairs(accepted) do if (point-g.point):length()<70 then duplicate=true end end
            if not duplicate then
                accepted[#accepted+1]=g.point
                local ref='ground_'..epoch..'_'..groundSerial..'_'..key
                groundTargets[ref]={point=g.point,origin=self.position,cell=Space.key(self.cell),time=core.getSimulationTime()}
                local d=g.point-self.position
                local level=require('scripts.astrabridge.mobility').waterLevel()
                local label=level and math.abs(g.point.z-level)<1 and 'Вода' or ({'Пол ниже','Пол','Пол выше'})[g.band]
                result[#result+1]={ref=ref,name=label..' '..({'слева','впереди','справа'})[g.side],
                    aim_point=P.array({g.x,g.y}),distance_m=round(g.distance),height_change_m=round(g.height),
                    bearing_deg=round(math.deg(M.angle(math.atan2(d.x,d.y)-camera.getYaw()))),
                    target_adjustment_m=round(adjustment),navigation=N.report(nav),actions=P.array({'walk'})}
            end
        end
    end
    return result
end
function M.resolveGround(ref)
    local g=groundTargets[ref]
    if g and g.cell==Space.key(self.cell) and (g.origin-self.position):length()<35
        and core.getSimulationTime()-g.time<3 then return g.point end
end
return M
