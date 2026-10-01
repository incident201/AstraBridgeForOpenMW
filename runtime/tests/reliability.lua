package.path='mod/?.lua;'..package.path
local G=require('scripts.astrabridge.guards')
local g={health=50,stop_on_damage=true,deadline=10,stop_health_pct=25}
assert(not G.check(g,0,{current=60,base=100}))
assert(G.check(g,1,{current=59,base=100})=='player_hurt')
assert(G.check(g,1,{current=20,base=100})=='health_low')
assert(G.check({deadline=1},1,{current=100,base=100})=='sequence_time_limit')
local P=require('scripts.astrabridge.progress')
local stalled={}
for i=0,25 do assert(not P.update(stalled,i*.1,1000+math.sin(i),math.sin(i)*5,0,0)) end
assert(P.update(stalled,2.6,1000,0,0,0)=='no_route_progress')
local walking={}
for i=0,100 do assert(not P.update(walking,i*.1,1000-i*10,i*10,0,0)) end
print('Continuous guards, oscillation detection and genuine path progress passed')
