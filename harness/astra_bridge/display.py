from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from .protocol import BridgeError, number


class Display:
    def __init__(self, root: Path, runtime: Path, name: str | None, headless: bool, width=1920, height=1080):
        self.root, self.runtime = root, runtime
        self.width, self.height = width, height
        self.name = name or os.environ.get("DISPLAY")
        self.headless, self.process, self.window = headless, None, None
        self.server_pid = None
        self.frame_stream = None
        self.media_stream = None
        self.sound = True
        self.env = os.environ.copy()
        self.env["LD_LIBRARY_PATH"] = str(root / "tools/usr/lib")
        self.xdotool = shutil.which("xdotool") or str(root / "tools/usr/bin/xdotool")

    def start(self):
        if self.headless:
            binary = shutil.which("Xvfb") or str(self.root / "tools/usr/bin/Xvfb")
            for index in range(94, 120):
                if not Path(f"/tmp/.X{index}-lock").exists() and not Path(f"/tmp/.X11-unix/X{index}").exists():
                    self.name = f":{index}"
                    break
            else:
                raise BridgeError("no_display_available")
            auth = self.runtime / "Xauthority"
            auth.touch(mode=0o600)
            import secrets
            xauth = shutil.which("xauth") or str(self.root / "tools/usr/bin/xauth")
            subprocess.run([xauth, "-f", str(auth), "add", self.name, ".", secrets.token_hex(16)],
                           env=self.env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.env["XAUTHORITY"] = str(auth)
            cmd = [binary, self.name, "-screen", "0", f"{self.width}x{self.height}x24",
                   "-nolisten", "tcp", "-auth", str(auth)]
            if not Path("/usr/bin/xkbcomp").exists():
                # The distro Xvfb has a compiled absolute xkbcomp path. A private mount
                # supplies that path without installing or changing system files.
                if not shutil.which("bwrap"):
                    raise BridgeError("install_xorg_xkbcomp_or_bubblewrap")
                cmd = ["bwrap", "--die-with-parent", "--ro-bind", "/", "/", "--bind", "/tmp", "/tmp",
                       "--tmpfs", "/usr/bin", "--ro-bind", shutil.which("bash"), "/usr/bin/sh",
                       "--ro-bind", str(self.root / "tools/usr/bin/xkbcomp"), "/usr/bin/xkbcomp", "--"] + cmd
            self.env["LIBGL_ALWAYS_SOFTWARE"] = "1"
            self.env.setdefault('LP_NUM_THREADS','2')
            with open(self.runtime / "xvfb.log", "w") as log:
                self.process = subprocess.Popen(cmd, env=self.env, stdout=log, stderr=log, start_new_session=True)
            deadline = time.monotonic() + 8
            while not Path(f"/tmp/.X11-unix/X{self.name[1:]}").exists():
                if self.process.poll() is not None or time.monotonic() > deadline:
                    raise BridgeError("virtual_display_failed")
                time.sleep(.05)
            lock_path=Path(f'/tmp/.X{self.name[1:]}-lock')
            if lock_path.exists():self.server_pid=int(lock_path.read_text().strip())
        if not self.name:
            raise BridgeError("display_required_use_headless")
        self.env["DISPLAY"] = self.name
        if self.env.get("XAUTHORITY"):
            os.environ["XAUTHORITY"] = self.env["XAUTHORITY"]

    def run(self, *args, timeout=4):
        p = subprocess.run([self.xdotool, *map(str, args)], env=self.env, capture_output=True, text=True, timeout=timeout)
        if p.returncode:
            raise BridgeError("input_failed")
        return p.stdout.strip()

    def focus(self, pid):
        ids = self.run("search", "--onlyvisible", "--pid", pid, "--class", "openmw").splitlines()
        if not ids:
            raise BridgeError("game_window_missing")
        self.window = ids[-1]
        self.run("windowfocus", "--sync", self.window)

    def geometry(self):
        if not self.window:
            raise BridgeError("game_window_missing")
        geometry = dict(line.split("=", 1) for line in self.run("getwindowgeometry", "--shell", self.window).splitlines())
        return {"left": int(geometry["X"]), "top": int(geometry["Y"]),
               "width": int(geometry["WIDTH"]), "height": int(geometry["HEIGHT"])}

    def capture(self, path: Path):
        if self.frame_stream and self.frame_stream.supported:
            size = self.frame_stream.capture(path)
            self.width, self.height = size['render_width'], size['render_height']
            return size
        from .window_capture import WindowCapture
        from .screenshots import save_bgra
        previous = os.environ.get("XAUTHORITY")
        if self.env.get("XAUTHORITY"):
            os.environ["XAUTHORITY"] = self.env["XAUTHORITY"]
        try:
            with WindowCapture(self.name,self.window) as screen:
                frame = screen.grab()
                size = save_bgra(path, frame.bgra, frame.width, frame.height)
        finally:
            if previous is None:
                os.environ.pop("XAUTHORITY", None)
            else:
                os.environ["XAUTHORITY"] = previous
        self.width,self.height=frame.width,frame.height
        return size

    def observation_size(self):
        from .screenshots import observation_size
        return observation_size(self.width,self.height)

    def native_point(self, x, y):
        w,h = self.observation_size()
        return x*self.width/w, y*self.height/h

    def public_coordinates(self, value):
        w,h = self.observation_size()
        sx,sy = w/self.width,h/self.height
        if isinstance(value, dict):
            return {k: [round(n*(sx if i%2==0 else sy),2) for i,n in enumerate(v)]
                    if k in {'rect','aim_point'} and isinstance(v,list) else self.public_coordinates(v)
                    for k,v in value.items()}
        if isinstance(value, list): return [self.public_coordinates(v) for v in value]
        return value

    def click(self, x, y, button=1):
        w,h = self.observation_size()
        number(x, 0, w-1); number(y, 0, h-1)
        x,y = self.native_point(x,y)
        if type(button) is not int or button not in {1, 2, 3}:
            raise BridgeError("invalid_arguments")
        self.run("mousemove", "--window", self.window, int(x), int(y))
        self.run("click", button)

    def key(self, key):
        # No console, debug bindings, system shortcuts or arbitrary chords.
        names = {"escape": "Escape", "enter": "Return", "tab": "Tab", "space": "space",
                 "up": "Up", "down": "Down", "left": "Left", "right": "Right",
                 "backspace": "BackSpace", "delete": "Delete", "pageup": "Prior", "pagedown": "Next"}
        if key not in names:
            raise BridgeError("invalid_key")
        self.run("key", "--clearmodifiers", names[key])

    def native_activate(self, profile):
        import xml.etree.ElementTree as ET
        # OpenMW 0.51 channel 9 is Activate; SDL scancode 44 is Space.
        # Fail closed if the profile was rebound; don't guess a key that might be the console.
        bindings = ET.parse(profile / 'input_v3.xml')
        control = bindings.find(".//Control[@name='9']/KeyBinder")
        if control is None or control.get('key') != '44':
            raise BridgeError('unsupported_activate_binding')
        self.run('windowfocus','--sync',self.window)
        self.run('key','--clearmodifiers','--delay','80','space')

    def text(self, text):
        if not isinstance(text, str) or not 1 <= len(text) <= 160 or any(ord(c) < 32 for c in text):
            raise BridgeError("invalid_text")
        self.run("type", "--clearmodifiers", "--delay", "20", "--", text, timeout=10)

    def native_rest(self, profile):
        import xml.etree.ElementTree as ET
        # Rest remains a legacy input action in OpenMW 0.51, not a Lua trigger.
        control = ET.parse(profile / 'input_v3.xml').find(".//Control[@name='13']/KeyBinder")
        if control is None or control.get('key') != '23':
            raise BridgeError('unsupported_rest_binding')
        self.run('key','--clearmodifiers','--delay','80','t')

    def stop(self):
        if self.media_stream:
            self.media_stream.close()
            self.media_stream = None
        if self.frame_stream:
            self.frame_stream.close()
            self.frame_stream = None
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=5)
        if self.headless and self.server_pid:
            # A namespace wrapper may exit before Xvfb removes its socket/lock.
            # Only clean the display we created, after its recorded server is gone.
            stat=Path(f'/proc/{self.server_pid}/stat')
            for _ in range(20):
                if not stat.exists() or stat.read_text().split(') ',1)[1].startswith('Z'):break
                time.sleep(.05)
            else:return
            lock=Path(f'/tmp/.X{self.name[1:]}-lock')
            if lock.exists() and lock.read_text().strip()==str(self.server_pid):
                Path(f'/tmp/.X11-unix/X{self.name[1:]}').unlink(missing_ok=True)
                lock.unlink(missing_ok=True)
        self.process = None
