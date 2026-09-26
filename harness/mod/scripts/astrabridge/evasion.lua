-- Bounded normal keyboard movement while another controller keeps the target in view.
local M={}
function M.new(direction,meters,seconds)
    return {direction=direction,meters=meters,limit=seconds,elapsed=0,travelled=0,stalled=0,moving=false}
end
function M.unit(direction,yaw)
    if direction=='forward' then return math.sin(yaw),math.cos(yaw) end
    if direction=='back' then return -math.sin(yaw),-math.cos(yaw) end
    local side=direction=='left' and -1 or 1
    return math.cos(yaw)*side,-math.sin(yaw)*side
end
local function finish(s,reason,obstacle)
    s.reason=reason;s.obstacle=obstacle;s.moving=false
    return {move=0,strafe=0,done=true,reason=reason}
end
function M.step(s,c,dt)
    if s.reason then return {move=0,strafe=0,done=true,reason=s.reason} end
    s.elapsed=s.elapsed+dt
    local moved=math.max(0,c.moved_m or 0)
    s.travelled=s.travelled+moved
    if c.dead then return finish(s,'player_down') end
    if not c.can_move then return finish(s,'cannot_act') end
    if not c.on_ground or c.swimming then return finish(s,'ground_required') end
    if s.travelled>=s.meters-.05 then return finish(s,'maneuver_complete') end
    if s.elapsed>=s.limit then return finish(s,'step_limit') end
    if s.moving and moved<.01 then s.stalled=s.stalled+dt else s.stalled=0 end
    if s.stalled>.8 then return finish(s,'maneuver_blocked','no_progress') end
    if not c.aligned then s.moving=false;return {move=0,strafe=0} end
    local remaining=s.meters-s.travelled
    local frame=math.max(.02,c.frame_distance_m or .1)
    local delay=c.input_delay_frames or 2
    local frames=math.max(1,delay)
    if not c.clear_m or c.clear_m<math.min(remaining,math.max(frame,moved)*frames)+.12 then
        return finish(s,'maneuver_blocked',c.obstacle or 'unknown_surface')
    end
    -- Stock action bindings can be two frames behind this controller. Account for
    -- movement already in flight before feeding more input, especially at low FPS.
    local amount=math.min(1,math.max(0,remaining-moved*delay)/math.max(.15,frame*frames))
    s.moving=amount>0
    return {move=s.direction=='back' and -amount or s.direction=='forward' and amount or 0,
        strafe=s.direction=='left' and -amount or s.direction=='right' and amount or 0}
end
function M.report(s)
    return {direction=s.direction,requested_m=s.meters,travelled_m=math.floor(s.travelled*100+.5)/100,
        elapsed=s.elapsed,blocked_by=s.obstacle}
end
return M
