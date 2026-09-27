"""Named places and directed door links learned from actual travel."""
import heapq
import json
import math
import uuid
import time


class AtlasRoutes:
    def route_outcomes(self, active=False):
        rows=[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM route_outcomes WHERE profile=? ORDER BY id DESC',(self.profile,))]
        if not active:return rows
        recent=[];succeeded=[]
        for row in rows:
            if row['success']:succeeded.append(row)
            elif row.get('retry_after',0)>time.time() and not any(s['kind']==row['kind'] and s['space']==row['space'] and s['destination']==row['destination'] and math.dist(s['origin'],row['origin'])<2 for s in succeeded):recent.append(row)
        return recent

    def outcome_history(self,args):
        from .information import page_rows
        rows=[]
        for row in self.route_outcomes():
            public={k:v for k,v in row.items() if k not in {'origin','position','retry_after'}}
            public['retry_in_seconds']=max(0,round(row.get('retry_after',0)-time.time(),1))
            space,node=self.find_node(row['destination'])
            if node:public['names']=node.get('names',[])
            rows.append(public)
        rows,meta=page_rows(rows,args)
        return {'attempts':rows,**meta,'source':'observed_route_outcomes'}

    def record_outcome(self, step, origin, action):
        reason=action.get('reason','unknown');success=reason=='arrived' or action.get('outcome')=='location_changed'
        current=self.current()
        row={'kind':step['kind'],'destination':step.get('ref',step.get('to')),'from':step.get('from'),
             'space':origin['space'],'origin':origin['pose'],'position':list(current['pose']) if current else None,
             'reason':reason,'success':success,'time':time.time(),'navigation':action.get('navigation',{}),
             'elapsed':action.get('elapsed',0),'turned_deg':action.get('motion',{}).get('turned_deg',0)}
        if not success and reason in {'blocked','no_progress','no_route_progress','repeated_positions','repeated_obstruction','no_path','endpoint_mismatch','height_mismatch','known_door_not_visible','activation_unconfirmed','out_of_reach','target_not_aimed'}:
            # Temporary actors must not permanently poison a learned route.
            row['retry_after']=row['time']+(8 if row['navigation'].get('blocked_by')=='actor' else 90)
        if success and step['kind']=='door':row['approach']=step.get('door',{})
        with self.db:self.db.execute('INSERT INTO route_outcomes(profile,payload) VALUES (?,?)',(self.profile,json.dumps(row,ensure_ascii=False)))
        self._route_cache=None
        return row

    def blocked_leg(self, failures, kind, destination, space, origin):
        return any(r['kind']==kind and r['destination']==destination and r['space']==space
                   and (math.dist(r['origin'],origin)<2 or r.get('position') and math.dist(r['position'],origin)<2) for r in failures)

    def graph_for(self, ref):
        return next((s for s in self.data['segments'] if s['ref']==ref and s.get('profile',self.profile)==self.profile),None)

    def find_node(self, ref):
        for s in self.data['segments']:
            if s.get('profile',self.profile)!=self.profile:continue
            n=next((n for n in s['nodes'] if n['ref']==ref),None)
            if n:return s,n
        matches=[(s,n) for s in self.data['segments'] if s.get('profile',self.profile)==self.profile
                 for n in s['nodes'] if ref in n.get('names',[])]
        if len(matches)==1:return matches[0]
        n=self.resolve(ref)
        return (self.current(),n) if n else (None,None)

    def anchor_node(self, name=None):
        s=self.current()
        if not s or 'pose' not in s:return None
        n=next((n for n in s['nodes'] if math.dist(n['p'],s['pose'])<.04),None)
        if n is None:
            serial=s.get('node_serial',0)+1;s['node_serial']=serial
            n={'ref':f"node_{s['ref']}_{serial}",'label':f'A{serial}','p':list(s['pose']),
               'visits':1,'views':[],'probes':[],'options':[],'walkable':True}
            s['nodes'].append(n)
        if name:n['names']=sorted(set(n.get('names',[])+[name]))
        s['current_node']=n['ref'];self.persist()
        return n

    def level_rows(self,s):
        # These are observed height bands, not inferred architectural floors.
        levels=s.setdefault('levels',[])
        for n in s['nodes']:
            if 'level' in n:continue
            near=[l for l in levels if abs(l['height']-n['p'][2])<=1.25]
            level=min(near,key=lambda l:abs(l['height']-n['p'][2])) if near else None
            if level is None:
                level={'ref':'level_'+uuid.uuid4().hex[:10],'label':f'L{len(levels)+1}','height':n['p'][2]}
                levels.append(level)
            n['level']=level['ref']
        return [{'ref':l['ref'],'label':l['label'],'height_change_m':round(l['height']-s['pose'][2],2),
                 'nodes':sum(n.get('level')==l['ref'] for n in s['nodes'])} for l in levels]

    def search(self,query='',space=None,page=0,limit=20,level=None):
        rows=[]
        for s in self.data['segments']:
            if s.get('profile',self.profile)!=self.profile or space and s['ref']!=space:continue
            levels=self.level_rows(s)
            ids={l['ref'] for l in levels if l['ref']==level or l['label']==level} if level else None
            for n in s['nodes']:
                if ids is not None and n.get('level') not in ids:continue
                text=' '.join([n['ref'],n['label'],*n.get('names',[]),*n.get('landmarks',[]),n.get('location',s['location'])])
                if query.casefold() not in text.casefold():continue
                row={'ref':n['ref'],'label':n['label'],'names':n.get('names',[]),'landmarks':n.get('landmarks',[]),
                     'space':s['ref'],'location':n.get('location',s['location']),'level':n.get('level'),
                     'current_space':s['ref']==self.segment,'visits':n.get('visits',0)}
                if s['ref']==self.segment:
                    d=[a-b for a,b in zip(n['p'],s['pose'])]
                    row.update(distance_m=round(math.hypot(*d[:2]),2),height_change_m=round(d[2],2))
                rows.append(row)
        rows.sort(key=lambda r:(not r['current_space'],r.get('distance_m',math.inf),r['location'],r['label']))
        start=page*limit
        with self.db:
            for s in self.data['segments']:
                if s.get('profile',self.profile)==self.profile:self._store(s)
        return {'nodes':rows[start:start+limit],'total':len(rows),'page':page,'limit':limit,
                'has_more':start+limit<len(rows),'source':'observed_places'}

    def transitions(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM transitions WHERE profile=?',(self.profile,))]

    def add_transition(self,origin,destination,door):
        a,an=self.find_node(origin);b,bn=self.find_node(destination)
        if not an or not bn or a['ref']==b['ref']:return None
        key=origin+'>'+destination
        link={'from':origin,'to':destination,'from_space':a['ref'],'to_space':b['ref'],
              'door':{k:door[k] for k in ('name','description','heading_deg') if door.get(k) is not None},'source':'observed_door_transition'}
        with self.db:self.db.execute('INSERT OR REPLACE INTO transitions VALUES (?,?,?)',(key,self.profile,json.dumps(link,ensure_ascii=False)))
        return link

    def import_transitions(self,path):
        if self._meta('door_imported:'+self.profile) or not path.exists():return
        before=None
        for line in path.open():
            try:entry=json.loads(line)
            except ValueError:continue
            result=entry.get('result',{});after=result.get('observation')
            if not isinstance(after,dict):continue
            action=result.get('action',{});args=entry.get('args',{})
            if before and action.get('outcome')=='location_changed':
                ref=args.get('target') if entry.get('op')=='act' else args.get('ref') if entry.get('op')=='interact' else None
                door=next((o for o in before.get('scene',{}).get('objects',[]) if o.get('ref')==ref and o.get('kind')=='door'),None)
                origin=before.get('exploration',{}).get('current_node');dest=after.get('exploration',{}).get('current_node')
                if door and origin and dest:self.add_transition(origin,dest,door)
            before=after
        self._set_meta('door_imported:'+self.profile,'1');self.db.commit()

    def route_to(self,ref):
        target_space,target=self.find_node(ref)
        if not target or not self.current():return None
        links=self.transitions();nodes={target['ref']:(target_space,target)}
        failures=self.route_outcomes(active=True)
        for link in links:
            for key in ('from','to'):
                s,n=self.find_node(link[key])
                if n:nodes[n['ref']]=(s,n)
        if failures:
            # Alternative waypoints are exclusively previously occupied nodes.
            for s in self.data['segments']:
                if s.get('profile',self.profile)==self.profile:
                    for n in s['nodes']:
                        if n.get('names') or n.get('visits',0)>1:nodes[n['ref']]=(s,n)
        costs={'@player':0};parents={};queue=[(0,'@player')]
        while queue:
            cost,key=heapq.heappop(queue)
            if cost!=costs[key]:continue
            if key==target['ref']:break
            if key=='@player':s=self.current();start=None
            else:s,n=nodes[key];start=n['p']
            routes,_,_=self.travelled_routes(start=start,space=s)
            edges=[]
            for dest,(ds,dn) in nodes.items():
                if ds['ref']!=s['ref'] or dest==key:continue
                if self.blocked_leg(failures,'walk',dest,s['ref'],start if start is not None else s['pose']):continue
                if dest in routes:edges.append((dest,routes[dest][1],{'kind':'walk','ref':dest,'source':'recorded_trail'}))
                elif math.dist(dn['p'],start if start is not None else s['pose'])<80:
                    # Door arrival markers rarely coincide with the point from
                    # which the door was activated. Both endpoints are known;
                    # ask the engine to bridge this gap when executing the leg.
                    edges.append((dest,math.dist(dn['p'],start if start is not None else s['pose']),
                                  {'kind':'walk','ref':dest,'source':'native_path_required'}))
            edges += [(l['to'],1,{'kind':'door',**l}) for l in links if l['from']==key and l['to'] in nodes
                      and not self.blocked_leg(failures,'door',l['to'],s['ref'],start if start is not None else s['pose'])]
            for dest,length,step in edges:
                candidate=cost+max(.01,length)
                if candidate<costs.get(dest,math.inf):
                    costs[dest]=candidate;parents[dest]=(key,step);heapq.heappush(queue,(candidate,dest))
        if target['ref'] not in costs:return None
        steps=[];key=target['ref']
        while key!='@player':key,step=parents[key];steps.append(step)
        return {'destination':target['ref'],'steps':list(reversed(steps)),'estimated_distance_m':round(costs[target['ref']],2),
                'source':'observed_paths_and_door_transitions'}
