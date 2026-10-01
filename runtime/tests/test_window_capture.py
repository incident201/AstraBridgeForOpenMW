"""Optional real X server test: ASTRA_TEST_DISPLAY=:101 pytest this file."""
import ctypes as C
import os
import pytest

from astra_bridge.protocol import BridgeError
from astra_bridge.window_capture import WindowCapture,bind


@pytest.mark.skipif(not os.environ.get('ASTRA_TEST_DISPLAY'),reason='needs an isolated X display')
def test_window_capture_excludes_covering_windows_and_survives_resize():
    display=os.environ['ASTRA_TEST_DISPLAY']
    x=C.CDLL('libX11.so.6')
    bind(x,'XOpenDisplay',C.c_void_p,[C.c_char_p]);bind(x,'XDefaultRootWindow',C.c_ulong,[C.c_void_p])
    bind(x,'XCreateSimpleWindow',C.c_ulong,[C.c_void_p,C.c_ulong,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_uint,C.c_ulong,C.c_ulong])
    bind(x,'XMapRaised',C.c_int,[C.c_void_p,C.c_ulong]);bind(x,'XSync',C.c_int,[C.c_void_p,C.c_int])
    bind(x,'XResizeWindow',C.c_int,[C.c_void_p,C.c_ulong,C.c_uint,C.c_uint])
    bind(x,'XDestroyWindow',C.c_int,[C.c_void_p,C.c_ulong]);bind(x,'XCloseDisplay',C.c_int,[C.c_void_p])
    conn=x.XOpenDisplay(display.encode());assert conn
    try:
        root=x.XDefaultRootWindow(conn)
        target=x.XCreateSimpleWindow(conn,root,20,20,80,60,0,0,0xff0000)
        x.XMapRaised(conn,target);x.XSync(conn,0)
        with WindowCapture(display,target) as capture:
            first=capture.grab();assert first.pixel(10,10)==(255,0,0)
            cover=x.XCreateSimpleWindow(conn,root,20,20,120,90,0,0,0x0000ff)
            x.XMapRaised(conn,cover);x.XSync(conn,0)
            assert capture.grab().pixel(10,10)==(255,0,0),'covering desktop content must not enter the capture'
            x.XResizeWindow(conn,target,100,70);x.XSync(conn,0)
            resized=capture.grab();assert (resized.width,resized.height)==(100,70)
            assert resized.pixel(10,10)==(255,0,0)
            x.XDestroyWindow(conn,target);x.XSync(conn,0)
            with pytest.raises(BridgeError):capture.grab()
    finally:x.XCloseDisplay(conn)
