package.path='mod/?.lua;'..package.path
local B=require('scripts.astrabridge.ballistics')
local function length(v)return math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)end
for _,dt in ipairs({1/60,.1,.2}) do
 for _,targetVelocity in ipairs({{x=0,y=0,z=0},{x=70,y=-20,z=0}}) do
  local target={x=0,y=2170,z=-350};local gravity=62.712;local speed=800
  local velocity,time=B.solve(target,targetVelocity,speed,gravity,dt)
  assert(velocity and time>0 and math.abs(length(velocity)-speed)<.01)
  -- Independent integration of the engine's gravity-before-movement update.
  local p={x=0,y=0,z=0};local v={x=velocity.x,y=velocity.y,z=velocity.z};local elapsed=0
  while elapsed<time do
   local part=math.min(dt,time-elapsed)
   v.z=v.z-gravity*dt
   for _,axis in ipairs({'x','y','z'}) do p[axis]=p[axis]+v[axis]*part end
   elapsed=elapsed+part
  end
  local error={x=p.x-target.x-targetVelocity.x*time,y=p.y-target.y-targetVelocity.y*time,z=p.z-target.z-targetVelocity.z*time}
  assert(length(error)<.7,'intercept error must stay below a centimetre at 5 FPS')
 end
end
assert(not B.solve({x=0,y=10000,z=0},{x=0,y=0,z=0},70,62,.2))
assert(not B.solve({x=0,y=100,z=0},{x=0,y=500,z=0},300,62,.2))
local state={}
B.sample(state,{x=0,y=0,z=0},.2)
local v=B.sample(state,{x=14,y=0,z=0},.2);assert(v.x>0 and v.x<70)
v=B.sample(state,{x=5000,y=0,z=0},.2);assert(v.x==0,'teleports are not observed continuous target velocity')
print('Ballistic aim: stationary/moving intercept, finite flight, low-FPS gravity integration and discontinuity checks passed')
