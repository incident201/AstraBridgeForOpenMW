"""Capture an X11/XWayland window's backing pixmap, never the desktop root.

XCB checked requests keep errors local to this connection (no process-global
Xlib error handler). Each recorder thread owns its own connection.
"""
from __future__ import annotations

import ctypes as C

from .protocol import BridgeError


class Cookie(C.Structure):
    _fields_=[('sequence',C.c_uint)]


class Geometry(C.Structure):
    _fields_=[('response_type',C.c_uint8),('depth',C.c_uint8),('sequence',C.c_uint16),
              ('length',C.c_uint32),('root',C.c_uint32),('x',C.c_int16),('y',C.c_int16),
              ('width',C.c_uint16),('height',C.c_uint16),('border',C.c_uint16),('pad',C.c_uint8*2)]


class Image(C.Structure):
    _fields_=[('response_type',C.c_uint8),('depth',C.c_uint8),('sequence',C.c_uint16),
              ('length',C.c_uint32),('visual',C.c_uint32),('pad',C.c_uint8*20)]


def bind(lib,name,restype,args):
    fn=getattr(lib,name);fn.restype=restype;fn.argtypes=args;return fn


class WindowCapture:
    backend='xcomposite_window'

    def __init__(self,display,window):
        self.window=int(window);self.conn=None
        self.x=C.CDLL('libxcb.so.1');self.composite=C.CDLL('libxcb-composite.so.0')
        self.free=bind(C.CDLL(None),'free',None,[C.c_void_p])
        bind(self.x,'xcb_connect',C.c_void_p,[C.c_char_p,C.POINTER(C.c_int)])
        bind(self.x,'xcb_disconnect',None,[C.c_void_p])
        bind(self.x,'xcb_connection_has_error',C.c_int,[C.c_void_p])
        bind(self.x,'xcb_generate_id',C.c_uint32,[C.c_void_p])
        bind(self.x,'xcb_flush',C.c_int,[C.c_void_p])
        bind(self.x,'xcb_request_check',C.c_void_p,[C.c_void_p,Cookie])
        bind(self.x,'xcb_free_pixmap',Cookie,[C.c_void_p,C.c_uint32])
        bind(self.x,'xcb_get_geometry',Cookie,[C.c_void_p,C.c_uint32])
        bind(self.x,'xcb_get_geometry_reply',C.POINTER(Geometry),[C.c_void_p,Cookie,C.POINTER(C.c_void_p)])
        bind(self.x,'xcb_get_image',Cookie,[C.c_void_p,C.c_uint8,C.c_uint32,C.c_int16,C.c_int16,C.c_uint16,C.c_uint16,C.c_uint32])
        bind(self.x,'xcb_get_image_reply',C.POINTER(Image),[C.c_void_p,Cookie,C.POINTER(C.c_void_p)])
        bind(self.x,'xcb_get_image_data',C.c_void_p,[C.POINTER(Image)])
        bind(self.x,'xcb_get_image_data_length',C.c_int,[C.POINTER(Image)])
        bind(self.composite,'xcb_composite_name_window_pixmap_checked',Cookie,[C.c_void_p,C.c_uint32,C.c_uint32])
        bind(self.composite,'xcb_composite_redirect_window_checked',Cookie,[C.c_void_p,C.c_uint32,C.c_uint8])
        self.conn=self.x.xcb_connect(display.encode() if display else None,None)
        if not self.conn or self.x.xcb_connection_has_error(self.conn):
            self.close();raise BridgeError('capture_display_unavailable')

    def close(self):
        if self.conn:self.x.xcb_disconnect(self.conn);self.conn=None

    def __enter__(self):return self
    def __exit__(self,*_):self.close()

    def _check(self,cookie):
        error=self.x.xcb_request_check(self.conn,cookie)
        if not error:return 0
        code=C.cast(error,C.POINTER(C.c_uint8))[1];self.free(error);return code

    def _reply(self,function,cookie):
        error=C.c_void_p();result=function(self.conn,cookie,C.byref(error))
        if error.value:
            self.free(error)
            if result:self.free(result)
            raise BridgeError('capture_window_unavailable')
        if not result:raise BridgeError('capture_window_unavailable')
        return result

    def grab(self):
        from mss.screenshot import ScreenShot
        pixmap=self.x.xcb_generate_id(self.conn)
        named=self._check(self.composite.xcb_composite_name_window_pixmap_checked(self.conn,self.window,pixmap))
        if named:
            # A bare X server has no compositor; request automatic redirection.
            # On KWin/XWayland the initial NameWindowPixmap already succeeds.
            if self._check(self.composite.xcb_composite_redirect_window_checked(self.conn,self.window,0)):
                raise BridgeError('capture_composite_unavailable')
            if self._check(self.composite.xcb_composite_name_window_pixmap_checked(self.conn,self.window,pixmap)):
                raise BridgeError('capture_window_unavailable')
        try:
            geometry=self._reply(self.x.xcb_get_geometry_reply,self.x.xcb_get_geometry(self.conn,pixmap))
            try:width,height,depth=geometry.contents.width,geometry.contents.height,geometry.contents.depth
            finally:self.free(geometry)
            if not width or not height or depth not in (24,32):raise BridgeError('capture_unsupported_pixel_format')
            reply=self._reply(self.x.xcb_get_image_reply,self.x.xcb_get_image(self.conn,2,pixmap,0,0,width,height,0xffffffff))
            try:
                size=self.x.xcb_get_image_data_length(reply)
                if size!=width*height*4:raise BridgeError('capture_unsupported_pixel_format')
                pixels=bytearray(C.string_at(self.x.xcb_get_image_data(reply),size))
            finally:self.free(reply)
            return ScreenShot(pixels,{'left':0,'top':0,'width':width,'height':height})
        finally:
            self.x.xcb_free_pixmap(self.conn,pixmap);self.x.xcb_flush(self.conn)
