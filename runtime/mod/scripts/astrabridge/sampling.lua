local M={}
-- A crowded city must not spend every visibility ray on actors behind walls.
-- Probe the nearest member of each category, then the second nearest, etc.
function M.order(candidates)
    local priority={actor=1,door=2,container=3,item=4,activator=5}
    table.sort(candidates,function(a,b)
        if a.kind~=b.kind then return priority[a.kind]<priority[b.kind] end
        return a.distance<b.distance
    end)
    local counts={}
    for _,g in ipairs(candidates) do
        counts[g.kind]=(counts[g.kind] or 0)+1;g.sampleOrder=counts[g.kind]
    end
    table.sort(candidates,function(a,b)
        if a.sampleOrder~=b.sampleOrder then return a.sampleOrder<b.sampleOrder end
        return priority[a.kind]<priority[b.kind]
    end)
end
return M
