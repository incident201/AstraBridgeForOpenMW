"""Independent playthrough data inside one managed state volume."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import time
import uuid

from astra_bridge.protocol import BridgeError
from .storage import Storage, write_json
from .profile_data import copy_data

# Default owns the original flat layout. Shared files/catalogs are not its data.
LEGACY_DATA=('profile','saves','sessions','atlas','configuration.json','storage.json','runtime','logs')


class Profiles:
    def __init__(self, root:Path, game:Path, installation:Path):
        self.root,self.game,self.installation=root,game,installation
        self.root.mkdir(parents=True,exist_ok=True);self.file=root/'profiles.json'
        if not self.file.exists():
            write_json(self.file,{'schema':1,'active':'default','profiles':[{'id':'default','name':'Default','legacy':True,'created':time.time()}]})
        self.data=json.loads(self.file.read_text())
        if self.data.get('schema')!=1:raise BridgeError('unsupported_profile_catalog')
        for row in list(self.data['profiles']):
            if row.get('deleting'):self._finish_delete(row['id'])

    def save(self):write_json(self.file,self.data)

    def get(self,key=None):
        key=key or self.data['active']
        row=next((p for p in self.data['profiles'] if p['id']==key),None)
        if row is None:raise BridgeError('profile_not_found')
        return row

    def path(self,key=None):
        row=self.get(key)
        return self.root if row.get('legacy') else self.root/'profiles'/row['id']

    def recordings(self,key=None):
        row=self.get(key)
        return self.root/'recordings' if row.get('legacy') else self.root/'recordings'/row['id']

    def public(self,key=None):
        row=self.get(key)
        return {k:row.get(k) for k in ('id','name','created')} | {
            'recordings_subdirectory':'' if row.get('legacy') else row['id'],'active':row['id']==self.data['active']}

    def catalog(self):return {'active':self.public(),'profiles':[self.public(p['id']) for p in self.data['profiles'] if not p.get('deleting')]}

    def validate_name(self,name,key=None):
        if not isinstance(name,str) or not name.strip() or len(name.strip())>80 or any(ord(c)<32 for c in name):raise BridgeError('invalid_profile_name')
        name=name.strip()
        if any(p['id']!=key and not p.get('deleting') and p['name'].casefold()==name.casefold() for p in self.data['profiles']):raise BridgeError('profile_name_exists')
        return name

    def _new(self,name,settings):
        key=uuid.uuid4().hex;storage=Storage(self.root/'profiles'/key,self.game,self.installation)
        if settings is not None:storage.update(copy.deepcopy(settings))
        (self.root/'recordings'/key).mkdir(parents=True,exist_ok=True)
        row={'id':key,'name':name,'created':time.time(),'legacy':False}
        self.data['profiles'].append(row);return row

    def create(self,name,settings=None):
        row=self._new(self.validate_name(name),settings);self.save();return self.public(row['id'])

    def rename(self,key,name):
        row=self.get(key);row['name']=self.validate_name(name,key);self.save();return self.public(key)

    def duplicate(self,key,name):
        source=self.path(key);name=self.validate_name(name)
        new=uuid.uuid4().hex;destination=self.root/'profiles'/new
        try:
            copy_data(source,destination,rebase=True)
            # Separate identity and files, including all SQLite and screenshot data.
            write_json(destination/'storage.json',{'schema':1,'installation_id':uuid.uuid4().hex,'created':time.time()})
            Storage(destination,self.game,self.installation)
            (self.root/'recordings'/new).mkdir(parents=True,exist_ok=True)
            self.data['profiles'].append({'id':new,'name':name,'created':time.time(),'legacy':False})
            self.save()
        except Exception:
            self.data['profiles']=[p for p in self.data['profiles'] if p['id']!=new]
            shutil.rmtree(destination,ignore_errors=True)
            shutil.rmtree(self.root/'recordings'/new,ignore_errors=True)
            raise
        return self.public(new)

    def select(self,key):
        row=self.get(key)
        if row.get('deleting'):raise BridgeError('profile_deletion_in_progress')
        self.data['active']=key;self.save();return self.public(key)

    def delete(self,key,settings=None):
        row=self.get(key)
        if self.data['active']==key:
            remaining=[p for p in self.data['profiles'] if p['id']!=key and not p.get('deleting')]
            self.data['active']=(remaining[0] if remaining else self._new('Default',settings))['id']
        row['deleting']=True;self.save()  # Never offer a partially deleted profile after a crash.
        self._finish_delete(key);return self.catalog()

    def _finish_delete(self,key):
        row=self.get(key)
        if self.data['active']==key:raise BridgeError('invalid_profile_deletion_state')
        targets=[self.root/name for name in LEGACY_DATA] if row.get('legacy') else [self.path(key)]
        for target in targets:
            if target.is_symlink() or target.is_file():target.unlink()
            elif target.is_dir():shutil.rmtree(target)
        # Videos are user media files on the host and are not reassigned to a new profile.
        self.data['profiles'].remove(row);self.save()
