"""Observed evidence, agent notes and private instance matching for learned names."""
import hashlib
import json
import sqlite3
import time
import uuid

from .information import page_rows
from .protocol import BridgeError, check_result
from .argument_specs import CHECKPOINT_SCHEMA, KNOWLEDGE_ACTION_FIELDS


class Knowledge:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS evidence (ref TEXT PRIMARY KEY, kind TEXT, title TEXT, text TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS notes (ref TEXT PRIMARY KEY, kind TEXT, text TEXT, status TEXT, evidence TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, payload TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS working_checkpoints (
                profile TEXT PRIMARY KEY, payload TEXT NOT NULL, branch TEXT NOT NULL,
                revision INTEGER NOT NULL, updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recognized_objects (
                profile TEXT NOT NULL, object_key TEXT NOT NULL, name TEXT NOT NULL,
                kind TEXT NOT NULL, actor_kind TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                object_ref TEXT,
                PRIMARY KEY (profile, object_key)
            );
        ''')
        # Additive migration preserves existing notes/evidence and learned names.
        with self.db:
            for table in ('notes', 'recognized_objects'):
                columns = {row[1] for row in self.db.execute('PRAGMA table_info('+table+')')}
                if 'object_ref' not in columns:
                    self.db.execute('ALTER TABLE '+table+' ADD COLUMN object_ref TEXT')
            missing = self.db.execute('SELECT profile,object_key FROM recognized_objects WHERE object_ref IS NULL').fetchall()
            for profile,key in missing:
                self.db.execute('UPDATE recognized_objects SET object_ref=? WHERE profile=? AND object_key=?',
                                ('object_'+uuid.uuid4().hex,profile,key))
            self.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS recognized_object_ref ON recognized_objects(object_ref)')

    def recognize(self, result, profile):
        """Strip private instance keys, then enrich current sightings from atlas-profile memory.

        No save checkpoint owns these rows. Only a permitted current inspection
        can write a name; matching a remembered instance never reads live detail.
        The private keys are deliberately absent from the public schema/receipts.
        """
        sightings = []

        def strip(value, depth=0):
            if isinstance(value, dict) and depth > 12:
                raise BridgeError('invalid_bridge_response')
            if isinstance(value, list):
                for child in value: strip(child, depth)
            elif isinstance(value, dict):
                has_key = '_recognition_key' in value
                key = value.pop('_recognition_key', None)
                is_sighting = isinstance(value.get('ref'), str) and value['ref'].startswith('visible_')
                if has_key or is_sighting and 'details_visible' in value:
                    if (not is_sighting or type(value.get('details_visible')) is not bool
                            or has_key and (not isinstance(key, str) or not 0 < len(key) <= 4096)):
                        raise BridgeError('invalid_bridge_response')
                    if key is not None and value.get('kind') not in {'actor','door','container','item','activator'}:
                        raise BridgeError('invalid_bridge_response')
                    if value.get('kind') == 'actor' and value.get('actor_kind') not in {'npc','creature'}:
                        raise BridgeError('invalid_bridge_response')
                    value.pop('name_source', None)
                    value.pop('memory_ref', None)
                    if not value['details_visible']:
                        value.pop('name', None)
                        value.pop('description', None)
                    elif 'name' in value:
                        if not isinstance(value['name'], str) or not 0 < len(value['name']) <= 4096:
                            raise BridgeError('invalid_bridge_response')
                        value['name_source'] = 'observed'
                    identity = json.dumps([key,value.get('kind'),value.get('actor_kind')],separators=(',', ':'))
                    sightings.append((value, hashlib.sha256(identity.encode()).hexdigest() if key else None))
                for child in value.values(): strip(child, depth+1)

        strip(result)
        check_result(result)  # Reject the entire packet before committing any knowledge.
        with self.db:
            for row, key in sightings:
                if key is None: continue
                now = time.time()
                self.db.execute('''INSERT INTO recognized_objects
                    (profile,object_key,name,kind,actor_kind,first_seen,last_seen,object_ref)
                    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(profile,object_key) DO NOTHING''',
                    (profile,key,'',row['kind'],row.get('actor_kind'),now,now,'object_'+uuid.uuid4().hex))
                # Category mismatches cannot transfer notes or names to a different object.
                if row['details_visible'] and row.get('name'):
                    self.db.execute('''UPDATE recognized_objects SET name=?,last_seen=?
                        WHERE profile=? AND object_key=? AND kind=? AND actor_kind IS ?''',
                        (row['name'],now,profile,key,row['kind'],row.get('actor_kind')))
            # Learn first so a repeated sighting in the same response is consistent.
            for row, key in sightings:
                if key is None: continue
                known = self.db.execute('''SELECT name,object_ref FROM recognized_objects
                    WHERE profile=? AND object_key=? AND kind=? AND actor_kind IS ?''',
                    (profile,key,row.get('kind'),row.get('actor_kind'))).fetchone()
                if known:
                    row['memory_ref'] = known[1]
                    if not row['details_visible'] and known[0]:
                        row['name'], row['name_source'] = known[0], 'remembered'
        return result

    def capture(self, kind, title, text):
        if not isinstance(text, str) or not text.strip(): return None
        ref = 'evidence_'+hashlib.sha256((kind+'\0'+title+'\0'+text).encode()).hexdigest()[:20]
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?)', (ref,kind,title,text,time.time()))
        return ref

    def ingest(self, op, result):
        if not isinstance(result,dict): return
        ui = result.get('ui', result if op=='ui' else {})
        dialogue = ui.get('dialogue',{})
        if dialogue.get('text'):
            ref=self.capture('dialogue',dialogue.get('speaker','Dialogue'),dialogue['text'])
            if ref: dialogue['evidence_ref']=ref
        if op=='read' and 'text' in result:
            result['evidence_ref']=self.capture('document',result.get('title','Opened document'),result['text'])
        if op=='inspect':
            for e in result.get('entries',[]):
                if e.get('text'): e['evidence_ref']=self.capture('journal',e.get('name','Journal'),e['text'])

    def event(self, payload):
        with self.db:
            cursor=self.db.execute('INSERT INTO events(payload,created) VALUES (?,?)',(json.dumps(payload,ensure_ascii=False),time.time()))
        return {'event_id':cursor.lastrowid, **payload}

    def _object(self, ref, profile):
        if not isinstance(ref,str) or not profile: raise BridgeError('unknown_object_memory')
        row=self.db.execute('SELECT object_ref,name,kind,actor_kind FROM recognized_objects WHERE object_ref=? AND profile=?',
                            (ref,profile)).fetchone()
        if not row: raise BridgeError('unknown_object_memory')
        result={'ref':row[0],'kind':row[2],'source':'observed_object_memory'}
        if row[1]:result.update(name=row[1],name_source='remembered')
        if row[3]:result['actor_kind']=row[3]
        return result

    def checkpoint_hint(self, profile, branch):
        row=self.db.execute('SELECT revision,branch FROM working_checkpoints WHERE profile=?',(profile,)).fetchone()
        if not row:return {'available':False}
        return {'available':True,'revision':row[0],'needs_revalidation':row[1]!=branch}

    def _checkpoint_references(self, payload, profile, place_lookup, *, strict):
        """Project only already-public memory; never geometry or transient handles."""
        result={}
        for field in ('evidence_refs','note_refs','object_refs','place_refs'):
            rows=[]
            for ref in payload.get(field,[]):
                try:
                    if field=='evidence_refs':
                        row=self.db.execute('SELECT kind,title,text FROM evidence WHERE ref=?',(ref,)).fetchone()
                        if not row:raise BridgeError('unknown_evidence')
                        item={'ref':ref,'kind':row[0],'title':row[1][:160],'excerpt':row[2][:160],'characters':len(row[2])}
                    elif field=='note_refs':
                        row=self.db.execute('SELECT kind,text,status,object_ref FROM notes WHERE ref=?',(ref,)).fetchone()
                        if not row:raise BridgeError('unknown_note')
                        if row[3]:self._object(row[3],profile)
                        item={'ref':ref,'kind':row[0],'excerpt':row[1][:160],'status':row[2],'characters':len(row[1])}
                        if row[3]:item['object_ref']=row[3]
                    elif field=='object_refs':
                        item=self._object(ref,profile)
                        if 'name' in item:item['name']=item['name'][:160]
                    else:
                        if place_lookup is None:raise BridgeError('unknown_place_memory')
                        item=place_lookup(ref)
                except BridgeError:
                    if strict:raise
                    item={'ref':ref,'unavailable':True}
                rows.append(item)
            result[{'evidence_refs':'evidence','note_refs':'notes','object_refs':'objects','place_refs':'places'}[field]]=rows
        return result

    def working_state(self, args, profile, branch, branch_reason=None, place_lookup=None):
        action=args.get('action')
        fields=KNOWLEDGE_ACTION_FIELDS.get(action,{'action'})
        if args.keys()-fields or not profile or not branch:raise BridgeError('invalid_arguments')
        if action=='checkpoint':
            payload=args.get('checkpoint')
            allowed=CHECKPOINT_SCHEMA['properties'].keys()
            if not isinstance(payload,dict) or payload.keys()-allowed:raise BridgeError('invalid_checkpoint')
            payload={**payload,'status':payload.get('status','open')}
            if not isinstance(payload['status'],str) or payload['status'] not in {'open','done','abandoned'}:raise BridgeError('invalid_checkpoint')
            for field in ('goal','next_step'):
                value=payload.get(field)
                if not isinstance(value,str) or len(value)>2000 or '\x00' in value:raise BridgeError('invalid_checkpoint')
                if (field=='goal' or payload['status']=='open') and not value.strip():raise BridgeError('invalid_checkpoint')
            for field,prefix in [('evidence_refs',('evidence_',)),('note_refs',('note_',)),
                                 ('object_refs',('object_',)),('place_refs',('node_','place_'))]:
                values=payload.setdefault(field,[])
                if (not isinstance(values,list) or len(values)>8
                    or any(not isinstance(v,str) or not v.startswith(prefix) or len(v)>200 or '\x00' in v for v in values)
                    or len(set(values))!=len(values)):raise BridgeError('invalid_checkpoint_reference')
            failures=payload.setdefault('failed_attempts',[])
            if (not isinstance(failures,list) or len(failures)>8
                or any(not isinstance(v,str) or not v.strip() or len(v)>600 or '\x00' in v for v in failures)):
                raise BridgeError('invalid_checkpoint')
            serialized=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
            if len(serialized.encode('utf-8'))>8192:raise BridgeError('checkpoint_too_large')
            with self.db:
                self._checkpoint_references(payload,profile,place_lookup,strict=True)
                self.db.execute('''INSERT INTO working_checkpoints VALUES (?,?,?,1,?)
                    ON CONFLICT(profile) DO UPDATE SET payload=excluded.payload,branch=excluded.branch,
                    revision=working_checkpoints.revision+1,updated=excluded.updated''',
                    (profile,serialized,branch,time.time()))
            return {'working_memory':self.checkpoint_hint(profile,branch),'source':'agent_checkpoint'}
        row=self.db.execute('SELECT payload,branch,revision,updated FROM working_checkpoints WHERE profile=?',(profile,)).fetchone()
        if not row:return {'working_memory':{'available':False},'checkpoint':None,'source':'agent_checkpoint'}
        payload=json.loads(row[0]);hint=self.checkpoint_hint(profile,branch)
        result={'working_memory':hint,'checkpoint':payload,'source':'agent_checkpoint',
                'branch':branch,'checkpoint_branch':row[1],'updated':row[3],
                'references':self._checkpoint_references(payload,profile,place_lookup,strict=False)}
        if hint['needs_revalidation']:result['revalidation_reason']=branch_reason or 'continuation_changed'
        return result

    def call(self, args, profile=None, *, branch=None, branch_reason=None, place_lookup=None):
        if args.get('action') in ('checkpoint','brief'):
            return self.working_state(args,profile,branch,branch_reason,place_lookup)
        if args.keys()-{'action','kind','text','ref','status','evidence','quote','query','page','limit','offset','object_ref'}:raise BridgeError('invalid_arguments')
        action=args.get('action','list')
        object_ref=args.get('object_ref')
        if object_ref is not None:
            if action not in {'add','list','objects'}:raise BridgeError('invalid_arguments')
            self._object(object_ref,profile)
        if action=='objects':
            if not profile:raise BridgeError('unknown_object_memory')
            refs=[object_ref] if object_ref else [r[0] for r in self.db.execute(
                'SELECT object_ref FROM recognized_objects WHERE profile=? ORDER BY first_seen DESC,object_ref',(profile,))]
            rows=[self._object(ref,profile) for ref in refs]
            for row in rows:
                row['notes_total']=self.db.execute('SELECT COUNT(*) FROM notes WHERE object_ref=?',(row['ref'],)).fetchone()[0]
            rows,meta=page_rows(rows,args)
            return {'objects':rows,**meta,'source':'observed_object_memory','historical':True}
        if action=='add':
            kind=args.get('kind','task');text=args.get('text')
            if kind not in {'note','task','fact','conversation'} or not isinstance(text,str) or not 1<=len(text)<=4000:raise BridgeError('invalid_arguments')
            evidence=args.get('evidence')
            if kind=='fact':
                source=self.db.execute('SELECT text FROM evidence WHERE ref=?',(evidence,)).fetchone()
                quote=args.get('quote')
                if not source or not isinstance(quote,str) or not quote.strip() or quote not in source[0]:raise BridgeError('observed_evidence_quote_required')
                evidence=json.dumps({'ref':evidence,'quote':quote},ensure_ascii=False)
            elif evidence:raise BridgeError('evidence_only_for_facts')
            ref='note_'+uuid.uuid4().hex[:16]
            with self.db:self.db.execute('INSERT INTO notes(ref,kind,text,status,evidence,created,object_ref) VALUES (?,?,?,?,?,?,?)',
                                         (ref,kind,text,'open',evidence,time.time(),object_ref))
            return {'ref':ref,'kind':kind,'text':text,'status':'open',**({'object_ref':object_ref} if object_ref else {}),
                    'source':'agent_note' if kind!='fact' else 'agent_summary_with_observed_evidence'}
        if action=='update':
            note=self.db.execute('SELECT object_ref FROM notes WHERE ref=?',(args.get('ref'),)).fetchone()
            if not note:raise BridgeError('unknown_note')
            if note[0]:self._object(note[0],profile)
            if args.get('status') not in {'open','done','abandoned'}:raise BridgeError('invalid_arguments')
            with self.db:cursor=self.db.execute('UPDATE notes SET status=? WHERE ref=?',(args['status'],args.get('ref')))
            if not cursor.rowcount:raise BridgeError('unknown_note')
            return {'ref':args['ref'],'status':args['status']}
        if action=='evidence':
            if args.get('ref'):
                row=self.db.execute('SELECT ref,kind,title,text FROM evidence WHERE ref=?',(args['ref'],)).fetchone()
                if not row:raise BridgeError('unknown_evidence')
                offset=args.get('offset',0);limit=args.get('limit',4000)
                if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=8000:raise BridgeError('invalid_arguments')
                return dict(zip(('ref','kind','title'),row[:3]),text=row[3][offset:offset+limit],offset=offset,next_offset=min(len(row[3]),offset+limit),characters=len(row[3]),eof=offset+limit>=len(row[3]))
            rows=[dict(zip(('ref','kind','title'),r[:3]),characters=len(r[3]),excerpt=r[3][:160]) for r in self.db.execute('SELECT ref,kind,title,text FROM evidence ORDER BY created DESC') if args.get('query','').casefold() in '\n'.join(r).casefold()]
            rows,meta=page_rows(rows,{k:v for k,v in args.items() if k!='query'})
            return {'evidence':rows,**meta}
        if action=='events':
            rows=[{'event_id':r[0],**json.loads(r[1])} for r in self.db.execute('SELECT id,payload FROM events ORDER BY id DESC')]
        elif action=='list':
            rows=[dict(zip(('ref','kind','text','status','evidence','object_ref'),r)) for r in self.db.execute('''
                SELECT n.ref,n.kind,n.text,n.status,n.evidence,n.object_ref FROM notes n
                LEFT JOIN recognized_objects o ON n.object_ref=o.object_ref
                WHERE (n.object_ref IS NULL OR o.profile=?) AND (? IS NULL OR n.object_ref=?)
                ORDER BY n.created DESC''',(profile,object_ref,object_ref))]
            for row in rows:
                if row['object_ref'] is None:row.pop('object_ref')
            rows=[r for r in rows if ('kind' not in args or r['kind']==args['kind']) and ('status' not in args or r['status']==args['status'])]
        else:raise BridgeError('invalid_arguments')
        rows,meta=page_rows(rows,args)
        return {'items':rows,**meta}
