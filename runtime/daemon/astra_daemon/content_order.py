"""Import TES3 load order using file timestamps and header master dependencies.

Only the initial TES3 header is read; world, character and quest records are not.
The INI numbers identify selected files, not the order used by Morrowind.
"""
from pathlib import Path
import struct
from astra_bridge.protocol import BridgeError


def masters(path, encoding):
    with path.open('rb') as stream:
        header=stream.read(16)
        # Leave non-TES3 formats to OpenMW (for example text .omwscripts).
        if len(header)!=16 or header[:4]!=b'TES3':return []
        size=struct.unpack_from('<I',header,4)[0]
        if size>1024*1024:raise BridgeError('invalid_content_header',message=f'The header of {path.name} is too large.')
        data=stream.read(size)
    if len(data)!=size:raise BridgeError('invalid_content_header',message=f'The header of {path.name} is incomplete.')
    result=[];position=0
    while position<len(data):
        if position+8>len(data):raise BridgeError('invalid_content_header',filename=path.name)
        kind,length=struct.unpack_from('<4sI',data,position);position+=8
        if position+length>len(data):raise BridgeError('invalid_content_header',filename=path.name)
        if kind==b'MAST':result.append(data[position:position+length].rstrip(b'\0').decode(encoding.replace('win','cp')))
        position+=length
    return result


def dependencies(directory, names, encoding):
    available={p.name.casefold():p for p in directory.iterdir() if p.is_file()}
    paths={};parents={}
    for name in names:
        if name.casefold() not in available:raise BridgeError('content_file_missing',message=f'Game file not found: {name}',filename=name)
        paths[name.casefold()]=available[name.casefold()]
    for key,path in paths.items():
        parents[key]=[name.casefold() for name in masters(path,encoding)]
        # OpenMW's importer explicitly orders the two official expansions.
        if key=='bloodmoon.esm' and 'tribunal.esm' in paths:parents[key].append('tribunal.esm')
        for parent in parents[key]:
            if parent not in paths:raise BridgeError('content_dependency_missing',message=f'{path.name} requires {parent}. Enable its master in Game data settings.',filename=path.name,master=parent)
    return paths,parents


def import_order(directory, names, encoding, *, by_timestamp=True):
    paths,parents=dependencies(directory,names,encoding)
    ordered=[];active=set();done=set()
    def visit(key):
        if key in done:return
        if key in active:raise BridgeError('content_dependency_cycle',message=f'Cyclic master dependency involving {paths[key].name}.')
        active.add(key)
        for parent in parents[key]:visit(parent)
        active.remove(key);done.add(key);ordered.append(paths[key].name)
    keys=sorted(paths,key=lambda k:(paths[k].stat().st_mtime_ns,paths[k].name)) if by_timestamp else paths
    for key in keys:visit(key)
    return ordered


def validate_order(directory, names, encoding):
    paths,parents=dependencies(directory,names,encoding);loaded=set()
    for name in names:
        key=name.casefold()
        for parent in parents[key]:
            if parent not in loaded:raise BridgeError('content_load_order',message=f'{paths[key].name} must load after {paths[parent].name}. Correct the content order in Game data settings.',filename=paths[key].name,master=paths[parent].name)
        loaded.add(key)
