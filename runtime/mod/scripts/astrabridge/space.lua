-- Private identity for a continuous coordinate space; exterior grid borders are not teleports.
local M={}
function M.key(cell)
    if cell.isExterior then return 'world:'..tostring(cell.worldSpaceId or 'default') end
    return cell.id
end
function M.label(cell,regions)
    if cell.displayName and cell.displayName~='' then return cell.displayName end
    local region=cell.region and regions and regions[cell.region]
    if region and region.name~='' then return region.name end
    return cell.isExterior and 'Wilderness' or (cell.name or '')
end
return M
