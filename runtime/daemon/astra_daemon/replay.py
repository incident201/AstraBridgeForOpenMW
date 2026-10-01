"""Read-only indexing of completed MP4 fragments for the Desktop replay viewer.

Never touches Recorder, engine clocks or ownership. The growing file is only
read; incomplete boxes are published after their complete payload is on disk.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import threading

from astra_bridge.protocol import BridgeError

MAX_METADATA = 4 * 1024 * 1024


def boxes(data, start=0):
    data=memoryview(data)
    while start + 8 <= len(data):
        size, kind = struct.unpack_from('>I4s', data, start)
        header = 8
        if size == 1:
            if start + 16 > len(data):raise ValueError('Incomplete extended box')
            size = struct.unpack_from('>Q', data, start + 8)[0];header = 16
        if size < header or start + size > len(data):raise ValueError('Invalid MP4 metadata box')
        yield kind, data[start + header:start + size]
        start += size
    if start != len(data):raise ValueError('Incomplete MP4 metadata')


def child(data, name):
    return next((value for kind, value in boxes(data) if kind == name), None)


def u32(data, offset):return struct.unpack_from('>I', data, offset)[0]
def u64(data, offset):return struct.unpack_from('>Q', data, offset)[0]


def track_info(moov):
    tracks = {};defaults = {}
    mvex = child(moov, b'mvex')
    for kind, data in boxes(mvex or b''):
        if kind == b'trex':defaults[u32(data, 4)] = u32(data, 12)
    for kind, trak in boxes(moov):
        if kind != b'trak':continue
        tkhd = child(trak, b'tkhd');mdia = child(trak, b'mdia')
        if tkhd is None or mdia is None:continue
        track_id = u32(tkhd, 20 if tkhd[0] else 12)
        mdhd = child(mdia, b'mdhd');hdlr = child(mdia, b'hdlr')
        if mdhd is None or hdlr is None:continue
        offset = 20 if mdhd[0] else 12
        scale = u32(mdhd, offset)
        if not scale:raise ValueError('Invalid media timescale')
        duration = (u64(mdhd, offset+4) if mdhd[0] else u32(mdhd, offset+4)) / scale
        media_time = 0
        edts = child(trak, b'edts');elst = child(edts, b'elst') if edts else None
        if elst and u32(elst, 4):
            if u32(elst, 4) != 1:raise ValueError('Unsupported edit list')
            media_time = struct.unpack_from('>q' if elst[0] else '>i', elst, 16 if elst[0] else 12)[0]
            if media_time < 0:raise ValueError('Unsupported empty edit')
        minf = child(mdia, b'minf');stbl = child(minf, b'stbl') if minf else None
        stsd = child(stbl, b'stsd') if stbl else None
        codec = None
        for sample_type, sample in boxes(stsd or b'', 8):
            if sample_type in (b'avc1', b'avc3'):
                avcc = child(sample[78:], b'avcC')
                if avcc and len(avcc) >= 4:codec = sample_type.decode()+'.'+avcc[1:4].hex()
            elif sample_type == b'mp4a':codec = 'mp4a.40.2'  # Recorder's AAC-LC contract.
        ctts = child(stbl, b'ctts') if stbl else None
        first_offset = struct.unpack_from('>i' if ctts[0] else '>I', ctts, 12)[0] if ctts and u32(ctts,4) else 0
        tracks[track_id] = {'kind':bytes(hdlr[8:12]), 'scale':scale, 'duration':duration,
                            'edit':media_time, 'codec':codec, 'default_duration':defaults.get(track_id,0),
                            'start':(first_offset-media_time)/scale}
    return tracks, mvex is not None


def fragment_times(moof, tracks):
    bounds=[]
    for kind, traf in boxes(moof):
        if kind != b'traf':continue
        tfhd = child(traf, b'tfhd');tfdt = child(traf, b'tfdt')
        if tfhd is None or tfdt is None:raise ValueError('Missing fragment timing')
        track = tracks.get(u32(tfhd,4))
        if not track or track['kind'] != b'vide':continue
        flags = u32(tfhd,0) & 0xffffff
        if flags & 1 or not flags & 0x020000:raise ValueError('Fragment must use moof-relative addressing')
        offset = 8 + (4 if flags & 2 else 0)
        default = u32(tfhd,offset) if flags & 8 else track['default_duration']
        decode = u64(tfdt,4) if tfdt[0] else u32(tfdt,4)
        for kind, trun in boxes(traf):
            if kind != b'trun':continue
            flags = u32(trun,0) & 0xffffff;count = u32(trun,4)
            if count > 100000:raise ValueError('Unreasonable fragment sample count')
            offset = 8 + (4 if flags & 1 else 0) + (4 if flags & 4 else 0)
            for _ in range(count):
                duration = u32(trun,offset) if flags & 0x100 else default
                offset += 4 if flags & 0x100 else 0
                offset += 4 if flags & 0x200 else 0
                offset += 4 if flags & 0x400 else 0
                composition = struct.unpack_from('>i' if trun[0] else '>I',trun,offset)[0] if flags & 0x800 else 0
                offset += 4 if flags & 0x800 else 0
                if not duration:raise ValueError('Missing sample duration')
                pts = (decode + composition - track['edit']) / track['scale']
                bounds.append((pts, pts+duration/track['scale']));decode += duration
    return (min(row[0] for row in bounds),max(row[1] for row in bounds)) if bounds else None


class RecordingIndex:
    def __init__(self, path):
        self.path = Path(path);self.generation=None
        self.cursor=0;self.init_parts=[];self.init=None;self.tracks={};self.fragmented=None
        self.pending=None;self.segments=[];self.origin=0.;self.end=0.;self.error=None

    def scan(self):
        try:
            with self.path.open('rb') as source:
                stat=os.fstat(source.fileno());generation=f'{stat.st_dev:x}-{stat.st_ino:x}'
                if self.generation != generation or stat.st_size < self.cursor:
                    self.__init__(self.path);self.generation=generation
                if self.fragmented is False:return
                while self.cursor+8 <= stat.st_size:
                    source.seek(self.cursor);header=source.read(16)
                    size,kind=struct.unpack_from('>I4s',header);header_size=8
                    if size==1:
                        if len(header)<16:break
                        size=u64(header,8);header_size=16
                    if size==0:break  # An open-ended box has no safe completed boundary.
                    if size<header_size:raise ValueError('Invalid MP4 box size')
                    if self.cursor+size>stat.st_size:break
                    if kind in (b'ftyp',b'moov',b'moof'):
                        if size>(64*1024*1024 if kind==b'moov' else MAX_METADATA):raise ValueError('MP4 metadata too large')
                        source.seek(self.cursor);raw=source.read(size);payload=raw[header_size:]
                        if kind==b'ftyp':self.init_parts=[raw]
                        elif kind==b'moov':
                            self.tracks,self.fragmented=track_info(payload)
                            video=next((t for t in self.tracks.values() if t['kind']==b'vide'),None)
                            if not video or not video['codec']:raise ValueError('Unsupported recording codec')
                            self.init=b''.join(self.init_parts+[raw]) if self.fragmented else b'file'
                            if not self.fragmented:
                                self.origin=max(0,video['start']);self.end=self.origin+video['duration']
                                return
                        else:self.pending=(self.cursor,fragment_times(payload,self.tracks))
                    elif kind==b'mdat' and self.pending:
                        start,times=self.pending
                        if times:
                            if not self.segments:self.origin=max(0,times[0])
                            self.end=max(self.end,times[1])
                            self.segments.append({'index':len(self.segments),'offset':start,'bytes':self.cursor+size-start,
                                                  'start':max(0,times[0]-self.origin),'end':max(0,times[1]-self.origin)})
                        self.pending=None
                    self.cursor+=size
        except FileNotFoundError:return
        except (ValueError,struct.error,IndexError) as exc:self.error=str(exc)

    def metadata(self, recording_id, active):
        codecs=[t['codec'] for t in self.tracks.values() if t['codec']]
        return {'id':recording_id,'name':self.path.name,'active':active,'generation':self.generation,
                'ready':bool(self.init and (self.segments or self.fragmented is False)),
                'kind':'fragmented' if self.fragmented is not False else 'file',
                'duration':max(0,self.end-self.origin),'offset':self.origin,'segments':len(self.segments),
                'mime':'video/mp4; codecs="'+', '.join(codecs)+'"','error':self.error}


class Replay:
    def __init__(self, directory):
        self.directory=Path(directory);self.indexes={};self.paths={};self.lock=threading.RLock();self.last=None

    def identify(self,path):
        path=Path(path)
        if path.parent.resolve()!=self.directory.resolve():raise BridgeError('invalid_recording_path')
        key=hashlib.sha256(path.name.encode()).hexdigest()[:32];self.paths[key]=path;return key

    def _get(self,key):
        if key not in self.paths:
            for path in self.directory.glob('*.mp4'):
                if not path.name.endswith('.finalizing.mp4') and hashlib.sha256(path.name.encode()).hexdigest()[:32]==key:
                    self.identify(path);break
        if key not in self.paths:raise BridgeError('recording_unavailable')
        if key not in self.indexes:
            if len(self.indexes)>=8:self.indexes.pop(next(iter(self.indexes)))
            self.indexes[key]=RecordingIndex(self.paths[key])
        value=self.indexes[key];value.scan();return value

    def info(self,active=None,key=None):
        with self.lock:
            active_key=self.identify(active) if active else None
            if active_key:self.last=active_key
            if key is None:key=active_key or self.last
            if key is None:return {'ready':False,'id':None,'duration':0,'active':False}
            return self._get(key).metadata(key,key==active_key)

    def batch(self,key,generation,when=None,after=None):
        with self.lock:
            value=self._get(key)
            if value.generation!=generation:raise BridgeError('replay_generation_changed')
            if after is not None:start=max(0,after+1)
            else:
                start=next((i for i,s in enumerate(value.segments) if s['end']>when),max(0,len(value.segments)-1))
                start=max(0,start-1)  # Include the previous closed GOP for decoder preroll.
            return value.segments[start:start+12]

    def part(self,key,generation,part):
        with self.lock:
            value=self._get(key)
            if value.generation!=generation:raise BridgeError('replay_generation_changed')
            if part=='init':return value.init
            if not part.isdigit() or int(part)>=len(value.segments):raise BridgeError('replay_segment_unavailable')
            segment=value.segments[int(part)]
            with value.path.open('rb') as stream:
                stat=os.fstat(stream.fileno())
                if f'{stat.st_dev:x}-{stat.st_ino:x}'!=generation:raise BridgeError('replay_generation_changed')
                stream.seek(segment['offset']);data=stream.read(segment['bytes'])
                if len(data)!=segment['bytes']:raise BridgeError('replay_segment_unavailable')
                return data
