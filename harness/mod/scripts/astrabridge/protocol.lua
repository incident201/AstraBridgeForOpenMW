-- Data only: no eval, object serialization, or arbitrary resource access.
local vfs = require('openmw.vfs')
local markup = require('openmw.markup')
local M = {}
local arrayMeta = {}
function M.array(t) return setmetatable(t or {}, arrayMeta) end
local function quote(s)
    return '"' .. s:gsub('[%z\1-\31\\"]', function(c)
        if c == '"' then return '\\"' end
        if c == '\\' then return '\\\\' end
        return string.format('\\u%04x', string.byte(c))
    end) .. '"'
end
local arrays = {items=true,spells=true,entries=true,saves=true,available=true,skills=true,topics=true,
    objects=true,actions=true,elements=true,rect=true,aim_point=true,messages=true,
    samples=true,rays=true,passages=true,steps=true,effects=true,ground_targets=true}
function M.encode(v, field)
    local t = type(v)
    if t == 'nil' then return 'null' end
    if t == 'boolean' then return v and 'true' or 'false' end
    if t == 'number' then
        assert(v == v and v ~= math.huge and v ~= -math.huge, 'nonfinite')
        return tostring(v)
    end
    if t == 'string' then return quote(v) end
    assert(t == 'table', 'non-data value')
    local parts = {}
    if arrays[field] or getmetatable(v) == arrayMeta or #v > 0 then
        for _, x in ipairs(v) do parts[#parts+1] = M.encode(x) end
        return '[' .. table.concat(parts, ',') .. ']'
    end
    for k, x in pairs(v) do
        assert(type(k) == 'string', 'non-string key')
        parts[#parts+1] = quote(k) .. ':' .. M.encode(x,k)
    end
    return '{' .. table.concat(parts, ',') .. '}'
end
local messageSerial=0
function M.emit(message)
    local encoded=M.encode(message)
    if #encoded<=1800 then print('ASTRA_BRIDGE '..encoded);return end
    messageSerial=messageSerial+1
    local token=(message.session or 'none')..':'..(message.id or 0)..':'..messageSerial
    local total=math.ceil(#encoded/700)
    for i=1,total do
        local part=encoded:sub((i-1)*700+1,i*700)
        local hex=part:gsub('.',function(c)return string.format('%02x',string.byte(c))end)
        print('ASTRA_PART '..token..' '..i..' '..total..' '..hex)
    end
end
function M.read()
    local f = vfs.open('astrabridge-runtime/inbox.json')
    local s = f:read(32769)
    f:close()
    if not s or #s > 32768 then return nil end
    local cmd = markup.decodeYaml(s)
    if type(cmd) ~= 'table' or cmd.version ~= 1 then return nil end
    if type(cmd.session) ~= 'string' or #cmd.session > 80 then return nil end
    if type(cmd.id) ~= 'number' or cmd.id < 1 or cmd.id % 1 ~= 0 then return nil end
    if type(cmd.op) ~= 'string' or type(cmd.args) ~= 'table' then return nil end
    return cmd
end
function M.reply(cmd, result, err)
    M.emit({version=1, session=cmd.session, id=cmd.id,
        status=err and 'rejected' or 'completed', result=result, error=err})
end
function M.inputAck(session,id)
    local f = vfs.open('astrabridge-runtime/input.json')
    local s = f:read(4096); f:close()
    local a = markup.decodeYaml(s or '{}')
    if a.session == session and a.id == id then return a.ok end
    return nil
end
function M.number(v, lo, hi, default)
    if v == nil then return default end
    assert(type(v) == 'number' and v == v and v >= lo and v <= hi, 'invalid number')
    return v
end
return M
