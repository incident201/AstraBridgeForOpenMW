package.path='mod/?.lua;'..package.path
local T=require('scripts.astrabridge.turning')
local S=require('scripts.astrabridge.space')
for _,dt in ipairs({1/60,.2,.8}) do
    local yaw,pitch=math.rad(350),0
    local done=false
    for _=1,200 do
        local before=yaw
        yaw,pitch,done=T.advance(yaw,pitch,math.rad(170),math.rad(30),dt)
        assert(math.abs(T.angle(yaw-before))<=T.speed*math.min(dt,.25)+1e-8)
        if done then break end
    end
    assert(done and math.abs(T.angle(yaw-math.rad(170)))<1e-6)
end
assert(T.delta(math.rad(359),math.rad(1),1/60)>0,'cross the zero heading by the short arc')
assert(T.delta(0,math.pi,.1)>0,'a positive half-turn must preserve the requested direction')
local a={id='exterior_1',isExterior=true,worldSpaceId='world'}
local b={id='exterior_2',isExterior=true,worldSpaceId='world'}
assert(S.key(a)==S.key(b),'outdoor cell borders must not clear locks or odometry')
assert(S.key(a)~=S.key({id='Room',isExterior=false}))
assert(S.key(a)~=S.key({id='exterior_1',isExterior=true,worldSpaceId='other'}))
assert(S.label({displayName='',region='private_region',isExterior=true},{private_region={name='Coast'}})=='Coast')
print('Finite camera speed, angle wrapping and continuous exterior spaces passed')
