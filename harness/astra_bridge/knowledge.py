"""Agent notes and evidence copied exclusively from public gameplay responses."""
import hashlib
import json
import sqlite3
import time
import uuid

from .information import page_rows
from .protocol import BridgeError


class Knowledge:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS evidence (ref TEXT PRIMARY KEY, kind TEXT, title TEXT, text TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS notes (ref TEXT PRIMARY KEY, kind TEXT, text TEXT, status TEXT, evidence TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, payload TEXT, created REAL);
        ''')

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

    def call(self, args):
        if args.keys()-{'action','kind','text','ref','status','evidence','quote','query','page','limit','offset'}:raise BridgeError('invalid_arguments')
        action=args.get('action','list')
        if action=='add':
            kind=args.get('kind','task');text=args.get('text')
            if kind not in {'task','fact','conversation'} or not isinstance(text,str) or not 1<=len(text)<=4000:raise BridgeError('invalid_arguments')
            evidence=args.get('evidence')
            if kind=='fact':
                source=self.db.execute('SELECT text FROM evidence WHERE ref=?',(evidence,)).fetchone()
                quote=args.get('quote')
                if not source or not isinstance(quote,str) or not quote.strip() or quote not in source[0]:raise BridgeError('observed_evidence_quote_required')
                evidence=json.dumps({'ref':evidence,'quote':quote},ensure_ascii=False)
            elif evidence:raise BridgeError('evidence_only_for_facts')
            ref='note_'+uuid.uuid4().hex[:16]
            with self.db:self.db.execute('INSERT INTO notes VALUES (?,?,?,?,?,?)',(ref,kind,text,'open',evidence,time.time()))
            return {'ref':ref,'kind':kind,'text':text,'status':'open','source':'agent_note' if kind!='fact' else 'agent_summary_with_observed_evidence'}
        if action=='update':
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
            rows=[dict(zip(('ref','kind','text','status','evidence'),r)) for r in self.db.execute('SELECT ref,kind,text,status,evidence FROM notes ORDER BY created DESC')]
            rows=[r for r in rows if ('kind' not in args or r['kind']==args['kind']) and ('status' not in args or r['status']==args['status'])]
        else:raise BridgeError('invalid_arguments')
        rows,meta=page_rows(rows,args)
        return {'items':rows,**meta}
