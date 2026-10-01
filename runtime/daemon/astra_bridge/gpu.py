"""Runtime GPU inventory and stable selectors; no host-specific device numbers."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import re
import subprocess

from .protocol import BridgeError

VENDORS={'0x8086':'intel','0x1002':'amd','0x10de':'nvidia'}


def pci_address(value):
    match=re.fullmatch(r'([0-9a-fA-F]{4,8}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])',value.strip())
    return f'{int(match[1],16):04x}:{match[2].lower()}:{match[3].lower()}.{match[4]}' if match else None


def inventory(sysfs=Path('/sys/class/drm'), devices=Path('/dev/dri')):
    result=[]
    for node in sorted(sysfs.glob('renderD*')):
        device=node/'device'
        pci=pci_address(device.resolve().name)
        if not pci:continue
        try:vendor=VENDORS.get((device/'vendor').read_text().strip(),'other')
        except OSError:vendor='other'
        label=f'{vendor.upper()} GPU ({pci})'
        try:
            text=subprocess.check_output(['lspci','-D','-s',pci],text=True,stderr=subprocess.DEVNULL,timeout=3).strip()
            if ': ' in text:label=text.split(': ',1)[1]
        except (OSError,subprocess.SubprocessError):pass
        render=devices/node.name
        result.append({'id':'pci:'+pci,'name':label,'vendor':vendor,'pci':pci,'render_node':str(render),
                       'accessible':os.access(render,os.R_OK|os.W_OK),'render_selectable':True,'nvenc_index':None})
    try:
        text=subprocess.check_output(['nvidia-smi','--query-gpu=pci.bus_id,name,uuid','--format=csv,noheader,nounits'],
                                     text=True,stderr=subprocess.DEVNULL,timeout=5)
        for line in text.splitlines():
            fields=[p.strip() for p in line.split(',')]
            if len(fields)!=3:continue
            pci=pci_address(fields[0])
            if not pci:continue
            row=next((r for r in result if r['pci']==pci),None)
            if row is None:
                row={'id':'pci:'+pci,'pci':pci,'vendor':'nvidia','render_node':None,'accessible':True,'render_selectable':True,'nvenc_index':None}
                result.append(row)
            row.update(name=fields[1],uuid=fields[2],accessible=True)
    except (OSError,subprocess.SubprocessError):pass
    cuda=cuda_devices()
    for row in result:
        row['nvenc_index']=cuda.get(row['pci'])
        row['encoding_candidates']=(['nvenc'] if row['nvenc_index'] is not None else [])+(['vaapi'] if row['render_node'] else [])
    nvidia=[r for r in result if r['vendor']=='nvidia']
    # PRIME's generic selector identifies a vendor, not an arbitrary GPU among
    # multiple NVIDIA cards. Do not pretend it provides exact device affinity.
    if len(nvidia)>1:
        for row in nvidia:
            row['render_selectable']=False
            row['render_unavailable_reason']='exact_nvidia_render_provider_mapping_required'
    return result


def cuda_devices():
    """Map CUDA ordinals to PCI identities in the encoder's inherited environment."""
    try:
        lib=ctypes.CDLL('libcuda.so.1')
        lib.cuInit.argtypes=[ctypes.c_uint];lib.cuInit.restype=ctypes.c_int
        lib.cuDeviceGetCount.argtypes=[ctypes.POINTER(ctypes.c_int)];lib.cuDeviceGetCount.restype=ctypes.c_int
        lib.cuDeviceGet.argtypes=[ctypes.POINTER(ctypes.c_int),ctypes.c_int];lib.cuDeviceGet.restype=ctypes.c_int
        lib.cuDeviceGetPCIBusId.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.c_int];lib.cuDeviceGetPCIBusId.restype=ctypes.c_int
        if lib.cuInit(0):return {}
        count=ctypes.c_int()
        if lib.cuDeviceGetCount(ctypes.byref(count)):return {}
        result={}
        for ordinal in range(count.value):
            device=ctypes.c_int();bus=ctypes.create_string_buffer(32)
            if lib.cuDeviceGet(ctypes.byref(device),ordinal)==0 and lib.cuDeviceGetPCIBusId(bus,len(bus),device.value)==0:
                pci=pci_address(bus.value.decode())
                if pci:result[pci]=ordinal
        return result
    except (OSError,AttributeError):return {}


def resolve_gpu(selector, rows=None):
    rows=inventory() if rows is None else rows
    row=next((item for item in rows if item['id']==selector),None)
    if row is None:raise BridgeError('selected_gpu_unavailable',gpu=selector)
    if not row.get('accessible',True):raise BridgeError('selected_gpu_access_denied',gpu=selector)
    return row
