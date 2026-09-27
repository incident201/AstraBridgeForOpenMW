-- Exercise the real menu dispatcher, including its independent watchdog.
package.path='mod/?.lua;'..package.path
local now,request=0,nil
local data,replies={},{}
local bus={setLifeTime=function()end,get=function(_,k)return data[k]end,
    getCopy=function(_,k)return data[k]end,set=function(_,k,v)data[k]=v end}
package.preload['openmw.storage']=function()return {LIFE_TIME={GameSession=1},playerSection=function()return bus end}end
package.preload['openmw.core']=function()return {getRealTime=function()return now end,sendGlobalEvent=function()end}end
package.preload['openmw.menu']=function()return {STATE={Running=1},getState=function()return 1 end}end
package.preload['openmw.vfs']=function()return {}end
package.preload['openmw.markup']=function()return {}end
local P=require('scripts.astrabridge.protocol')
P.read=function()return request end
P.reply=function(cmd,result,err)replies[cmd.id]={result=result,error=err}end
local menu=require('scripts.astrabridge.menu')
local function tick(seconds)now=now+seconds;menu.engineHandlers.onFrame()end
for id,op in ipairs({'act','track'}) do
    request={id=id,session='duration',op=op,args={seconds=140}}
    tick(.03)
    assert(data.request.id==id)
    for _=1,140 do tick(1);assert(not replies[id],'dispatcher timed out before the action duration')end
    data.response={id=id,session='duration',result={elapsed=140,paused=true}}
    tick(.03)
    assert(replies[id] and not replies[id].error)
end
request={id=3,session='duration',op='act',args={seconds=10}}
tick(.03);data.cancel=false
tick(100)
assert(replies[3].error=='game_operation_timeout' and data.cancel,'a stalled engine must still time out')
print('Long durations survive the dispatcher; stalled requests still cancel')
