package.path='mod/?.lua;'..package.path
local mode,primary='Vanity','FirstPerson'
local disabled,previewDisabled=false,false
package.preload['openmw.camera']=function()return {MODE={Vanity='Vanity',Preview='Preview',FirstPerson='FirstPerson'},
    getMode=function()return mode end,setMode=function(v)mode=v end}end
package.preload['openmw.interfaces']=function()return {Camera={
    getPrimaryMode=function()return primary end,
    disableModeControl=function(tag)assert(tag=='AstraBridge');disabled=true end,
    disableStandingPreview=function(tag)assert(tag=='AstraBridge');previewDisabled=true end,
}}end
local policy=require('scripts.astrabridge.camera_policy')
policy.apply();assert(disabled and previewDisabled and mode=='FirstPerson')
mode='ThirdPerson';policy.apply();assert(mode=='ThirdPerson')
mode='Static';policy.apply();assert(mode=='Static','do not override scripted cutscenes')
mode='Preview';primary='ThirdPerson';policy.apply();assert(mode=='ThirdPerson')
print('Idle orbit disabled, detached mode recovered, ordinary/cutscene views preserved')
