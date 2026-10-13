-- Exercise the real menu transport across the player-storage reset of a UI load.
package.path = 'mod/?.lua;' .. package.path
local data, incoming, replies = {}, nil, {}
local now, running = 0, true
local bus = {
    setLifeTime=function() end,
    set=function(_, key, value) data[key]=value end,
    get=function(_, key) return data[key] end,
    getCopy=function(_, key) return data[key] end,
}
package.preload['openmw.storage']=function()
    return {playerSection=function() return bus end, LIFE_TIME={GameSession=1}}
end
package.preload['openmw.core']=function()
    return {getRealTime=function() return now end, sendGlobalEvent=function() end}
end
package.preload['openmw.menu']=function()
    return {STATE={Running=1,Ended=2},getState=function() return running and 1 or 0 end}
end
package.preload['scripts.astrabridge.protocol']=function()
    return {
        readCancel=function() end, read=function() return incoming end,
        actionTimeout=function() return 20 end,
        reply=function(cmd,result,err) replies[cmd.id]={result=result,error=err} end,
    }
end
local menu=require('scripts.astrabridge.menu')
local function tick() now=now+.03; menu.engineHandlers.onFrame() end
local function request(id,op,args)
    incoming={session='fixture',id=id,op=op,args=args or {}}
    tick()
    return incoming
end
local function resetPlayer()
    data.request=nil;data.response=nil;data.ready=false
end

local read=request(1,'observe',{_passive=true})
assert(data.request==read)
resetPlayer();tick()
assert(not data.request,'Do not query the player before initialization finishes')
data.ready=true;tick()
assert(data.request==read,'Restore a passive read lost during a manual load')
data.response={session='fixture',id=1,result={ui_mode='Gameplay'}};tick()
assert(replies[1].result.ui_mode=='Gameplay' and not replies[1].error)

local action=request(2,'act',{seconds=1})
assert(data.request==action)
resetPlayer();data.ready=true;tick()
assert(not data.request,'Never replay a state-changing action across a load')
-- Stop can still interrupt the old command.
running=false
request(3,'stop',{_runtime_mode='manual'})
assert(replies[2].error=='cancelled')
assert(replies[3].result.ui_mode=='MainMenu')
request(4,'observe',{_passive=true})
assert(replies[4].result.ui_mode=='MainMenu','Main-menu reads need no player')

running=true
request(5,'observe',{_passive=true})
resetPlayer()
request(6,'stop',{_runtime_mode='idle'})
assert(replies[5].error=='cancelled','Releasing manual control cancels its read')
data.ready=true;tick()
assert(data.request.id==6,'Do not restore a cancelled observation')
print('Manual save loading: passive reads recover, mutations never replay, cancellation preserved')
