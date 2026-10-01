package.path='mod/?.lua;'..package.path
local E=require('scripts.astrabridge.evasion')
local function context(moved,clear)
 return {moved_m=moved or 0,clear_m=clear or 2,frame_distance_m=.2,
   on_ground=true,swimming=false,can_move=true,aligned=true}
end
for _,direction in ipairs({'forward','back','left','right'}) do
 local s=E.new(direction,2,4)
 local c=E.step(s,context(),.1)
 assert(not c.done)
 assert(direction~='back' or c.move<0 and c.strafe==0)
 assert(direction~='left' or c.strafe<0 and c.move==0)
 assert(direction~='right' or c.strafe>0 and c.move==0)
 assert(direction~='forward' or c.move>0 and c.strafe==0)
 c=E.step(s,context(2),.1);assert(c.done and c.reason=='maneuver_complete')
end
local s=E.new('back',2,4);local c=context();c.aligned=false
assert(E.step(s,c,.1).move==0,'face the selected target before moving')
s=E.new('left',2,4);c=E.step(s,context(0,.1),.1)
assert(c.done and c.reason=='maneuver_blocked','never strafe into unknown/blocked space')
s=E.new('right',2,4);c=context();c.swimming=true
assert(E.step(s,c,.1).reason=='ground_required')
s=E.new('back',2,4);c=context();c.dead=true
assert(E.step(s,c,.1).reason=='player_down')
s=E.new('right',2,.2);assert(E.step(s,context(),.2).reason=='step_limit')
s=E.new('left',2,4)
for _=1,12 do c=E.step(s,context(),.1) end
assert(c.reason=='maneuver_blocked' and E.report(s).blocked_by=='no_progress')
local x,y=E.unit('back',0);assert(x==0 and y==-1)
x,y=E.unit('right',0);assert(x==1 and y==0)
x,y=E.unit('left',math.pi/2);assert(math.abs(x)<1e-8 and math.abs(y-1)<1e-8)
print('Evasion: backward/strafe axes, face target, obstacle, ground, death, distance and time limits passed')
