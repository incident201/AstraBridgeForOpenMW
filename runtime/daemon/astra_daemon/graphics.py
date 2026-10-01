from __future__ import annotations

import os
from pathlib import Path
import re
import signal
import subprocess
import time

from astra_bridge.protocol import BridgeError
from astra_bridge.gpu import resolve_gpu


def application_environment(base, gpu='auto'):
    env=base.copy()
    for key in ('__NV_PRIME_RENDER_OFFLOAD','__GLX_VENDOR_LIBRARY_NAME','__VK_LAYER_NV_optimus',
                '__NV_PRIME_RENDER_OFFLOAD_PROVIDER','DRI_PRIME','MESA_D3D12_DEFAULT_ADAPTER_NAME'):
        env.pop(key,None)
    row=resolve_gpu(gpu) if gpu.startswith('pci:') else None
    if row and not row['render_selectable']:
        raise BridgeError(row['render_unavailable_reason'],gpu=gpu)
    nvidia=gpu=='nvidia' or row and row['vendor']=='nvidia'
    if env.get('ASTRA_GPU_BACKEND')=='wsl':
        env['GALLIUM_DRIVER']='d3d12'
        if row:env['MESA_D3D12_DEFAULT_ADAPTER_NAME']=row['name']
        elif nvidia:env['MESA_D3D12_DEFAULT_ADAPTER_NAME']='NVIDIA'
    elif nvidia:
        env.update(__NV_PRIME_RENDER_OFFLOAD='1',__GLX_VENDOR_LIBRARY_NAME='nvidia',__VK_LAYER_NV_optimus='NVIDIA_only')
    elif row:
        env['DRI_PRIME']='pci-'+row['pci'].replace(':','_').replace('.','_')
    return env


class Graphics:
    def __init__(self, installation, storage):
        self.installation,self.storage=installation,storage
        self.process=None
        self.environment={**os.environ,'SDL_VIDEODRIVER':'x11'}
        self.info={}
        self.log=None
        self.software=False

    def start(self, software=False, gpu='auto'):
        if not isinstance(gpu,str) or gpu not in ('auto','nvidia') and not gpu.startswith('pci:'):raise BridgeError('invalid_graphics_gpu')
        if self.process and self.process.poll() is None:
            if self.software!=software:self.close()
            else:
                self.environment=application_environment(self.environment,gpu)
                if not self.probe(software,gpu):raise BridgeError('graphics_probe_failed')
                return self.environment['DISPLAY']
        self.software=software
        self.environment=application_environment(self.environment,'auto')
        directory=Path(os.environ.get('XDG_RUNTIME_DIR','/tmp/astra-display'))
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        directory.chmod(0o700)
        sockets=Path('/tmp/.X11-unix')
        sockets.mkdir(mode=0o1777,exist_ok=True)
        sockets.chmod(0o1777)
        self.environment['XDG_RUNTIME_DIR']=str(directory)
        self.environment['WAYLAND_DISPLAY']='astra-wayland'
        self.environment['SDL_AUDIODRIVER']='dummy'
        if software:self.environment['LIBGL_ALWAYS_SOFTWARE']='1'
        else:self.environment.pop('LIBGL_ALWAYS_SOFTWARE',None)
        log=self.storage/'logs/weston.log'
        self.log=log.open('w')
        command=['weston','--backend=headless-backend.so','--use-gl','--xwayland',
                 '--width=1920','--height=1080','--idle-time=0','--socket=astra-wayland',
                 '--config='+str(self.installation/'runtime/graphics/weston.ini'),
                 '--modules='+str(self.installation/'runtime/graphics/virtual-seat.so')]
        self.process=subprocess.Popen(command,env=self.environment,stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if self.process.poll() is not None:
                raise BridgeError('private_display_failed',diagnostic='weston.log')
            match=re.search(r'xserver listening on display (:[0-9]+)',log.read_text(errors='replace'))
            if match:
                self.environment['DISPLAY']=match.group(1)
                self.environment=application_environment(self.environment,gpu)
                if self.probe(software,gpu):return match.group(1)
            time.sleep(.1)
        raise BridgeError('private_display_timeout')

    def probe(self, software, gpu):
        result=subprocess.run(['glxinfo','-B'],env=self.environment,capture_output=True,text=True,timeout=10)
        if result.returncode:
            if gpu=='nvidia':raise BridgeError('nvidia_gl_unavailable_check_driver_cdi',diagnostic=result.stderr[-1000:])
            return False
        renderer=next((line.split(':',1)[1].strip() for line in result.stdout.splitlines()
                       if line.startswith('OpenGL renderer string:')),'unknown')
        software_renderer=any(x in renderer.lower() for x in ('llvmpipe','softpipe','software rasterizer','swrast','swiftshader','basic render','lavapipe'))
        accelerated=not software_renderer and renderer!='unknown' and not re.search(r'Accelerated:\s*no',result.stdout)
        version=re.search(r'OpenGL core profile version string:\s*(\d+)\.(\d+)',result.stdout)
        if not version or tuple(map(int,version.groups()))<(3,3):
            raise BridgeError('opengl_3_3_required',renderer=renderer)
        self.info={'renderer':renderer,'hardware_accelerated':bool(accelerated),'requested_gpu':gpu,
                   'display':self.environment['DISPLAY'],'backend':'weston-headless-xwayland','probe':result.stdout}
        if not software and not accelerated:raise BridgeError('hardware_gl_required',renderer=renderer)
        selected=resolve_gpu(gpu) if gpu.startswith('pci:') else None
        if (gpu=='nvidia' or selected and selected['vendor']=='nvidia') and 'nvidia' not in renderer.lower():
            raise BridgeError('requested_gpu_not_selected',requested=gpu,renderer=renderer)
        if selected:self.info['selected_device']=selected
        return True

    def close(self):
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid,signal.SIGTERM)
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid,signal.SIGKILL);self.process.wait()
        if self.log:self.log.close()
        self.process=None
