package.path='mod/?.lua;'..package.path
math.atan2=math.atan2 or math.atan
local F=require('scripts.astrabridge.flight')
local T=require('scripts.astrabridge.turning')
for _,dt in ipairs({1/60,.12,.22}) do
    for _,goal in ipairs({{0,0,560},{0,0,-420},{350,490,280}}) do
        local p={0,0,0};local yaw,pitch,travelled=0,0,0
        local s=F.new(15,goal[1]==0 and goal[2]==0);local reason
        for _=1,1000 do
            local c=F.step(s,{x=goal[1]-p[1],y=goal[2]-p[2],z=goal[3]-p[3],yaw=yaw,pitch=pitch,
                levitation=true,travelled=travelled,speed=600},dt)
            if c.reason then reason=c.reason;break end
            yaw=yaw+T.delta(yaw,c.yaw,dt);pitch=pitch+T.delta(pitch,c.pitch,dt)
            travelled=c.move*175*dt
            p[1]=p[1]+math.sin(yaw)*math.cos(pitch)*travelled
            p[2]=p[2]+math.cos(yaw)*math.cos(pitch)*travelled
            p[3]=p[3]-math.sin(pitch)*travelled
        end
        assert(reason=='arrived','flight must converge at low FPS: '..tostring(reason))
        if goal[1]==0 and goal[2]==0 then assert(math.abs(yaw)<.01,'vertical flight must preserve heading') end
    end
end
local s=F.new(15)
local context={x=0,y=100,z=0,yaw=0,pitch=0,levitation=true,travelled=0,speed=600}
local result
for _=1,20 do result=F.step(s,context,.1);if result.reason then break end end
assert(result.reason=='blocked','wall contact must stop the motor')
context.travelled=3
s=F.new(15)
for i=1,30 do
    context.y=100+i%2*2
    result=F.step(s,context,.1)
    if result.reason then break end
end
assert(result.reason=='blocked','contact jitter must not reset the progress timeout')
s=F.new(15,true)
for i=1,30 do
    result=F.step(s,{x=i*2,y=0,z=-140,yaw=0,pitch=math.rad(89.5),levitation=true,speed=600},.1)
    if result.reason then break end
    assert(result.yaw==0,'lateral floor sliding must not rotate a vertical descent')
end
assert(result.reason=='blocked')
context.levitation=false
assert(F.step(F.new(15),context,.1).reason=='levitation_ended')
context.levitation=true
assert(F.step(F.new(.2),context,.2).reason=='step_limit')
print('Flight convergence, collision stop, effect expiry and bounded action passed')
