"""Bounded XTest input for the private Xwayland server; no host input access."""
import ctypes as C
import math
import subprocess

from astra_bridge.protocol import BridgeError

KEYS={
    'Enter':'Return','Escape':'Escape','Space':'space','Tab':'Tab','Backspace':'BackSpace',
    'ShiftLeft':'Shift_L','ShiftRight':'Shift_R','ControlLeft':'Control_L','ControlRight':'Control_R',
    'AltLeft':'Alt_L','AltRight':'Alt_R','MetaLeft':'Super_L','MetaRight':'Super_R',
    'ArrowUp':'Up','ArrowDown':'Down','ArrowLeft':'Left','ArrowRight':'Right',
    'Home':'Home','End':'End','PageUp':'Prior','PageDown':'Next','Delete':'Delete','Insert':'Insert',
    'CapsLock':'Caps_Lock','Minus':'minus','Equal':'equal','BracketLeft':'bracketleft',
    'BracketRight':'bracketright','Backslash':'backslash','Semicolon':'semicolon','Quote':'apostrophe',
    'Backquote':'grave','Comma':'comma','Period':'period','Slash':'slash',
    **{'Key'+chr(i):chr(i).lower() for i in range(65,91)},
    **{'Digit'+str(i):str(i) for i in range(10)},**{'F'+str(i):'F'+str(i) for i in range(1,13)},
}


def bind(lib,name,result,*arguments):
    function=getattr(lib,name);function.restype=result;function.argtypes=arguments
    return function


class Input:
    def __init__(self,display,env):
        self.env=env
        self.x=C.CDLL('libX11.so.6');self.test=C.CDLL('libXtst.so.6')
        bind(self.x,'XInitThreads',C.c_int)()
        self.d=bind(self.x,'XOpenDisplay',C.c_void_p,C.c_char_p)(display.encode())
        if not self.d:raise BridgeError('input_display_unavailable')
        self.flush=bind(self.x,'XFlush',C.c_int,C.c_void_p)
        self.keysym=bind(self.x,'XStringToKeysym',C.c_ulong,C.c_char_p)
        self.keycode=bind(self.x,'XKeysymToKeycode',C.c_ubyte,C.c_void_p,C.c_ulong)
        self.key=bind(self.test,'XTestFakeKeyEvent',C.c_int,C.c_void_p,C.c_uint,C.c_int,C.c_ulong)
        self.button=bind(self.test,'XTestFakeButtonEvent',C.c_int,C.c_void_p,C.c_uint,C.c_int,C.c_ulong)
        self.motion=bind(self.test,'XTestFakeMotionEvent',C.c_int,C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_ulong)
        self.relative=bind(self.test,'XTestFakeRelativeMotionEvent',C.c_int,C.c_void_p,C.c_int,C.c_int,C.c_ulong)
        self.held_keys=set();self.held_buttons=set()

    def event(self,event):
        if not isinstance(event,dict):raise BridgeError('invalid_input')
        kind=event.get('type')
        if kind=='key':
            if type(event.get('down')) is not bool or event.get('code') not in KEYS:raise BridgeError('invalid_key')
            code=self.keycode(self.d,self.keysym(KEYS[event['code']].encode()))
            if not code:raise BridgeError('unmapped_key')
            self.key(self.d,code,int(event['down']),0)
            (self.held_keys.add if event['down'] else self.held_keys.discard)(code)
        elif kind=='button':
            if type(event.get('down')) is not bool or event.get('button') not in (0,1,2):raise BridgeError('invalid_button')
            button={0:1,1:2,2:3}[event['button']]
            self.button(self.d,button,int(event['down']),0)
            (self.held_buttons.add if event['down'] else self.held_buttons.discard)(button)
        elif kind in ('pointer','relative'):
            x,y=event.get('x'),event.get('y')
            if any(type(n) not in (int,float) or not math.isfinite(n) for n in (x,y)):raise BridgeError('invalid_pointer')
            if kind=='pointer':
                if not 0<=x<=1 or not 0<=y<=1:raise BridgeError('invalid_pointer')
                self.motion(self.d,-1,round(x*1919),round(y*1079),0)
            else:
                if abs(x)>4096 or abs(y)>4096:raise BridgeError('invalid_pointer')
                self.relative(self.d,round(x),round(y),0)
        elif kind=='wheel':
            steps=event.get('steps')
            if type(steps) is not int or not -10<=steps<=10:raise BridgeError('invalid_wheel')
            for _ in range(abs(steps)):
                button=4 if steps>0 else 5
                self.button(self.d,button,1,0);self.button(self.d,button,0,0)
        elif kind=='release':self.release()
        elif kind=='text':
            text=event.get('text')
            if not isinstance(text,str) or len(text)>1024 or '\x00' in text:raise BridgeError('invalid_text')
            subprocess.run(['xdotool','type','--clearmodifiers','--',text],env=self.env,check=True,timeout=10)
        else:raise BridgeError('invalid_input')
        self.flush(self.d)

    def release(self):
        for code in self.held_keys:self.key(self.d,code,0,0)
        for button in self.held_buttons:self.button(self.d,button,0,0)
        self.held_keys.clear();self.held_buttons.clear();self.flush(self.d)

    def close(self):
        self.release()
        bind(self.x,'XCloseDisplay',C.c_int,C.c_void_p)(self.d)
