import base64
import hashlib
import json
import os
import struct
from pathlib import Path


class ResourceFailure(ValueError):pass


class Resources:
    def __init__(self,skill,journal):
        self.skill=Path(skill).resolve();self.journal=journal;self.images={};self.paths={}
        self.references={p.stem:p.resolve() for p in (self.skill/'references').glob('*.md')
                         if p.resolve().is_relative_to(self.skill)}

    def restore(self):
        path=self.journal.root/'images.json'
        if not path.exists():return
        self.images=json.loads(path.read_text(encoding='utf-8'))
        for ref,info in self.images.items():
            if ref!=info['image_ref'] or not Path(info['path']).resolve().is_relative_to((self.journal.root/'images').resolve()):
                raise ResourceFailure('Invalid image archive in saved session.')
        self.paths={(info['original_path'],info['sha256']):ref for ref,info in self.images.items()}

    def read_reference(self,ref):
        if ref not in self.references:raise ResourceFailure('Unknown skill reference ID.')
        path=self.references[ref]
        if not path.resolve().is_relative_to(self.skill):raise ResourceFailure('Reference is outside the exported skill.')
        return {'ok':True,'result':{'reference':ref,'text':path.read_text(encoding='utf-8')}}

    def register(self,path,roots,call_id):
        path=Path(path).resolve(strict=True)
        if not any(path.is_relative_to(root.resolve()) for root in roots):raise ResourceFailure('Image is outside this profile\'s public artifact directory.')
        if not path.is_file():raise ResourceFailure('Image is not a regular file.')
        if path.stat().st_size>32*1024*1024:raise ResourceFailure('Image exceeds the API image size limit.')
        data=path.read_bytes();dimensions={}
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime,extension='image/png','.png'
            if len(data)>=24:dimensions=dict(zip(('width','height'),struct.unpack('>II',data[16:24])))
        elif data.startswith(b'\xff\xd8\xff'):mime,extension='image/jpeg','.jpg'
        elif data[:6] in (b'GIF87a',b'GIF89a'):mime,extension='image/gif','.gif'
        elif data[:4]==b'RIFF' and data[8:12]==b'WEBP':mime,extension='image/webp','.webp'
        else:raise ResourceFailure('Unsupported image format.')
        digest=hashlib.sha256(data).hexdigest();key=(str(path),digest)
        if key in self.paths:return self.paths[key]
        destination=self.journal.root/'images'/(digest+extension)
        if not destination.exists():
            fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:out.write(data)
        ref=f'image_{len(self.images)+1:06}'
        info={'image_ref':ref,'original_path':str(path),'path':str(destination),'sha256':digest,
              'mime':mime,'bytes':len(data),'tool_call_id':call_id,**dimensions}
        self.images[ref]=info;self.paths[key]=ref
        self.journal.write('images.json',self.images);self.journal.event('image',**info)
        return ref

    def collect(self,result,roots,call_id):
        refs=[];by_path={};errors=[]
        def visit(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if (key=='screenshot' or key=='image' and value.get('view_mode') in ('local','world')
                            or key=='png') and isinstance(item,str):
                        try:
                            ref=self.register(item,roots,call_id);by_path[item]=ref
                            if ref not in refs:refs.append(ref)
                        except (OSError,ResourceFailure) as exc:errors.append({'path':item,'error':str(exc)})
                    else:visit(item)
            elif isinstance(value,list):
                for item in value:visit(item)
        visit(result)
        current=result.get('result',{})
        preferred=None
        if isinstance(current,dict):
            preferred=current.get('map',{}).get('image')
            final=current.get('final',{})
            observation=current.get('observation',{})
            preferred=preferred or (final.get('screenshot') if isinstance(final,dict) else None)
            preferred=preferred or (observation.get('screenshot') if isinstance(observation,dict) else None) or current.get('screenshot') or current.get('png')
        # Images quoted in place memory or old receipts are registered but do
        # not silently replace the current view. The model may request them.
        selected=by_path.get(preferred)
        augmented={**result}
        if refs:augmented['image_refs']=[{**{k:v for k,v in self.images[ref].items() if k!='path'},'selected':ref==selected} for ref in refs]
        if errors:augmented['image_errors']=errors
        return augmented,selected

    def saved_image(self,ref):
        if ref not in self.images:raise ResourceFailure('Unknown image_ref; arbitrary file paths are not accepted.')
        info=self.images[ref]
        return {'ok':True,'result':{k:v for k,v in info.items() if k!='path'},'historical':True},ref

    def content(self,ref):
        info=self.images[ref];path=Path(info['path']).resolve(strict=True)
        if not path.is_relative_to((self.journal.root/'images').resolve()):raise ResourceFailure('Invalid archived image path.')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=info['sha256']:raise ResourceFailure('Archived image was modified.')
        return {'type':'image_url','image_url':{'url':'data:'+info['mime']+';base64,'+base64.b64encode(data).decode(),'detail':'original'}}


RESOURCE_TOOLS=[
    {'type':'function','function':{'name':'read_skill_reference','description':'Read a complete reference from the exported gameplay skill by ID. No arbitrary file access.',
        'parameters':{'type':'object','properties':{'reference':{'type':'string'}},'required':['reference'],'additionalProperties':False}}},
    {'type':'function','function':{'name':'view_saved_image','description':'View an image previously returned by a game tool, using its image_ref. Historical images are not current game state.',
        'parameters':{'type':'object','properties':{'image_ref':{'type':'string'}},'required':['image_ref'],'additionalProperties':False}}},
]
