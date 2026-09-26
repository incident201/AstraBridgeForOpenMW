package.path='mod/?.lua;'..package.path
local candidates={}
for i=1,50 do candidates[#candidates+1]={kind='actor',distance=i} end
candidates[#candidates+1]={kind='door',distance=10}
candidates[#candidates+1]={kind='door',distance=3}
candidates[#candidates+1]={kind='activator',distance=20}
require('scripts.astrabridge.sampling').order(candidates)
assert(candidates[1].kind=='actor' and candidates[1].distance==1)
assert(candidates[2].kind=='door' and candidates[2].distance==3)
assert(candidates[3].kind=='activator')
assert(candidates[5].kind=='door' and candidates[5].distance==10)
assert(#candidates==53)
print('Visible doors and signs cannot be starved by a crowd of occluded actors')
