package.path='mod/?.lua;'..package.path
local calls=0
package.preload['openmw.nearby']=function()return {
    _astraActorSweep=function()calls=calls+1;return {hit=false},1 end,
}end
package.preload['openmw.self']=function()return {object={}}end
package.preload['openmw.types']=function()return {}end
package.preload['openmw.camera']=function()return {}end
local clock={}
package.preload['openmw.core']=function()return clock end
package.preload['openmw.util']=function()return {}end
package.preload['scripts.astrabridge.protocol']=function()return {}end
package.preload['scripts.astrabridge.space']=function()return {}end
package.preload['scripts.astrabridge.mobility']=function()return {}end
local T=require('scripts.astrabridge.terrain')
local function search()
    for i=1,350 do T.bodyContact(0,1) end
    return 'supported route'
end
local task=T.queryTask(search,400)
local done,result,slices=false,nil,0
while not done do
    local count
    done,result,count=T.resumeQueryTask(task,80)
    assert(count<=80,'A search slice must respect its per-frame query budget')
    slices=slices+1
    -- Ordinary movement checks must not inherit a suspended search's budget.
    T.bodyContact(0,1)
end
assert(result=='supported route' and slices==5 and calls==355)
task=T.queryTask(search,200)
local total=0
repeat
    local count
    done,result,count=T.resumeQueryTask(task,80);total=total+count
until done
assert(result==nil and total==200,'A resumed search must retain the total query cap')
assert(T.withQueryBudget(1,function()T.bodyContact(0,1);T.bodyContact(0,1);return true end)==nil)
T.bodyContact(0,1)
local now=0
clock.getRealTime=function()now=now+.001;return now end
local timed=T.queryTask(search,400)
local timedSlices=0
repeat
    local count
    done,result,count=T.resumeQueryTask(timed,160)
    assert(count<=4,'The time budget must yield even before the query count cap')
    timedSlices=timedSlices+1
until done
assert(result=='supported route' and timedSlices>80)
print('Incremental collision search: slice and total budgets, yielded state and normal checks isolated')
