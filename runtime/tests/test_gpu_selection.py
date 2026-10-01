import subprocess

import pytest

from astra_bridge import encoding as E, gpu as G
from astra_bridge.protocol import BridgeError
from astra_daemon.graphics import application_environment


def card(vendor='intel', ordinal=None):
    return {'id':'pci:0000:02:00.0','pci':'0000:02:00.0','name':vendor+' GPU','vendor':vendor,
            'render_node':'/dev/dri/renderD129','nvenc_index':ordinal,'render_selectable':True}


def test_explicit_encoding_gpu_is_never_replaced_by_another_gpu(monkeypatch,tmp_path):
    selected=card();calls=[]
    monkeypatch.setattr(E,'resolve_gpu',lambda _:selected)
    monkeypatch.setattr(E,'binaries',lambda _: (['pinned'],False))
    monkeypatch.setattr(E,'available',lambda _:({'h264_nvenc','h264_vaapi','libx264','aac'},'version'))
    def probe(encoder,*_):calls.append(encoder);return encoder.codec=='libx264','failed'
    monkeypatch.setattr(E,'probe',probe)
    encoder,attempts=E.select({},60,True,tmp_path,E.settings({'encoding_gpu':selected['id']}))
    assert encoder.codec=='libx264'
    assert all(c.device==selected['render_node'] and c.gpu_id==selected['id'] for c in calls[:-1])
    assert all(c.codec!='h264_nvenc' for c in calls)
    with pytest.raises(BridgeError,match='recording_encoder_unavailable'):
        E.select({},60,True,tmp_path,E.settings({'encoding_gpu':selected['id'],'recording_encoder':'vaapi'}))


def test_nvidia_encoder_uses_cuda_ordinal_for_chosen_pci_device(monkeypatch,tmp_path):
    selected=card('nvidia',3)
    monkeypatch.setattr(E,'resolve_gpu',lambda _:selected)
    monkeypatch.setattr(E,'binaries',lambda _: (['pinned'],False))
    monkeypatch.setattr(E,'available',lambda _:({'h264_nvenc','aac'},'version'))
    monkeypatch.setattr(E,'probe',lambda *_:(True,None))
    encoder,_=E.select({},60,True,tmp_path,E.settings({'encoding_gpu':selected['id']}))
    command=encoder.command(1920,1080,60,'out.mp4')
    assert command[command.index('-gpu')+1]=='3'
    assert encoder.info()['gpu_id']==selected['id']


def test_missing_explicit_gpu_reports_actionable_error(monkeypatch,tmp_path):
    monkeypatch.setattr(G,'inventory',lambda:[])
    with pytest.raises(BridgeError,match='selected_gpu_unavailable'):
        E.select({},60,True,tmp_path,E.settings({'encoding_gpu':card()['id']}))


def test_rendering_selection_clears_previous_gpu_env_and_preserves_driver_paths(monkeypatch):
    import astra_daemon.graphics as graphics
    monkeypatch.setattr(graphics,'resolve_gpu',lambda _:card())
    original={'LD_LIBRARY_PATH':'/injected/driver','DRI_PRIME':'1','__GLX_VENDOR_LIBRARY_NAME':'nvidia',
              'MESA_D3D12_DEFAULT_ADAPTER_NAME':'stale'}
    env=application_environment(original,card()['id'])
    assert env['DRI_PRIME']=='pci-0000_02_00_0' and env['LD_LIBRARY_PATH']=='/injected/driver'
    assert '__GLX_VENDOR_LIBRARY_NAME' not in env and 'MESA_D3D12_DEFAULT_ADAPTER_NAME' not in env
    env=application_environment(env,'nvidia')
    assert env['__NV_PRIME_RENDER_OFFLOAD']=='1' and 'DRI_PRIME' not in env
    env=application_environment(env,'auto')
    assert '__NV_PRIME_RENDER_OFFLOAD' not in env


def test_inventory_merges_drm_and_nvidia_by_pci_not_number(monkeypatch,tmp_path):
    device=tmp_path/'pci/0000:02:00.0';device.mkdir(parents=True);(device/'vendor').write_text('0x10de')
    node=tmp_path/'drm/renderD129';node.mkdir(parents=True);(node/'device').symlink_to(device)
    devices=tmp_path/'devices';devices.mkdir();(devices/'renderD129').touch()
    def output(command,**_):
        return '00000000:02:00.0, NVIDIA Test, GPU-test\n' if command[0]=='nvidia-smi' else '0000:02:00.0 VGA controller: NVIDIA Test'
    monkeypatch.setattr(G.subprocess,'check_output',output);monkeypatch.setattr(G,'cuda_devices',lambda:{'0000:02:00.0':3})
    rows=G.inventory(tmp_path/'drm',devices)
    assert len(rows)==1 and rows[0]['nvenc_index']==3 and rows[0]['uuid']=='GPU-test'
    assert rows[0]['id']=='pci:0000:02:00.0'


def test_ambiguous_nvidia_render_selection_is_not_guessed(monkeypatch,tmp_path):
    monkeypatch.setattr(G.subprocess,'check_output',lambda *a,**k:'00000000:02:00.0, NVIDIA A, GPU-a\n00000000:03:00.0, NVIDIA B, GPU-b\n')
    monkeypatch.setattr(G,'cuda_devices',lambda:{'0000:02:00.0':0,'0000:03:00.0':1})
    rows=G.inventory(tmp_path,tmp_path)
    assert len(rows)==2 and all(not row['render_selectable'] for row in rows)
    assert all('nvenc' in row['encoding_candidates'] for row in rows)
