"""Observation-backed place graph. It never reads game saves or world geometry."""
from __future__ import annotations
import json
from pathlib import Path
import time
import uuid
from .protocol import BridgeError


class SpatialMemory:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {
            'version': 1, 'branch': uuid.uuid4().hex[:8], 'places': [], 'links': [], 'route': [], 'anchor': None}

    def persist(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2)+'\n')
        temporary.replace(self.path)

    def attach_atlas(self,atlas):
        """Upgrade old notes only when an existing marker or image proves the link."""
        changed=False
        for place in self.data['places']:
            if place.get('atlas_node'):continue
            views={v.get('screenshot') for v in place.get('views',[]) if v.get('screenshot')}
            matches=[]
            for graph in atlas.data['segments']:
                if graph.get('profile',atlas.profile)!=atlas.profile:continue
                for node in graph['nodes']:
                    same_marker=place.get('motor_ref') and place['motor_ref']==node.get('motor_ref')
                    if same_marker or views.intersection(node.get('views',[])):matches.append(node)
            if len(matches)==1:
                place['atlas_node']=matches[0]['ref'];changed=True
        if changed:self.persist()

    def branch(self, reason):
        self.data['branch'] = uuid.uuid4().hex[:8]
        self.data['anchor'] = None
        self.data['route'] = []
        self.data['branch_reason'] = reason
        self.persist()

    def remember(self, label, note, exits, confidence, observation):
        if not isinstance(label, str) or not 1 <= len(label) <= 120:
            raise BridgeError('invalid_place_label')
        if not isinstance(note, str) or len(note) > 4000 or confidence not in {'observed', 'inferred'}:
            raise BridgeError('invalid_place_note')
        if not isinstance(exits, list) or len(exits) > 12 or any(not isinstance(x, str) or len(x) > 200 for x in exits):
            raise BridgeError('invalid_place_exits')
        if not observation or observation.get('state') != 'running':
            raise BridgeError('observation_required')
        place = next((p for p in self.data['places'] if p['branch'] == self.data['branch'] and p['label'] == label), None)
        if place is None:
            place = {'ref': 'place_'+uuid.uuid4().hex[:10], 'label': label, 'branch': self.data['branch'], 'views': []}
            self.data['places'].append(place)
        place.update(note=note, exits=exits, confidence=confidence, location=observation.get('location',''), seen_at=time.time())
        place['views'].append({k: observation[k] for k in ('observation','screenshot','orientation') if k in observation})
        if observation.get('terrain',{}).get('supported'):
            place['local_passages']=observation['terrain']['passages']
            place['local_map']=observation.get('local_map')
        place['views'] = place['views'][-6:]
        place['visible_names'] = [x['name'] for x in observation.get('scene', {}).get('objects', [])]
        self.data['anchor'] = {'place': place['ref'], 'status': 'recognized', 'source': 'agent_label'}
        self.persist()
        return place

    def recall(self, query='', archived=False):
        if not isinstance(query, str) or len(query) > 200 or type(archived) is not bool:
            raise BridgeError('invalid_arguments')
        places = [p for p in self.data['places'] if (archived or p['branch'] == self.data['branch'])
                  and query.casefold() in (p['ref']+' '+p['label']+' '+p['note']).casefold()]
        ids = {p['ref'] for p in places}
        return {'branch': self.data['branch'], 'anchor': self.data['anchor'], 'places': places[-30:],
                'links': [l for l in self.data['links'] if l['from'] in ids or l['to'] in ids]}

    def connect(self, origin, destination, via):
        places = {p['ref']: p for p in self.data['places'] if p['branch'] == self.data['branch']}
        if origin not in places or destination not in places or origin == destination:
            raise BridgeError('unknown_place')
        if not isinstance(via, str) or not 1 <= len(via) <= 1000:
            raise BridgeError('invalid_route_note')
        link = {'from': origin, 'to': destination, 'via': via, 'branch': self.data['branch'],
                'confidence': 'agent_reported', 'evidence': self.data['route'][-12:]}
        self.data['links'].append(link)
        self.persist()
        return link

    def record_step(self, op, args, result, observation):
        motion = result.get('motion')
        changes=result.get('changes',{})
        if not motion and changes.get('location_changed'):motion={'location_changed':True}
        if not motion:
            return
        if self.data['anchor'] and (motion.get('moved_m', 0) > .15 or motion.get('location_changed')):
            self.data['anchor']['status'] = 'last_seen_not_current'
        self.data['route'].append({'op': op, 'inputs': args, 'motion': motion, 'reason': result.get('reason'),
                                   'observation': observation.get('observation'), 'screenshot': observation.get('screenshot'),
                                   'location': observation.get('location')})
        self.data['route'] = self.data['route'][-60:]
        self.persist()

    def observe_location(self,observation):
        anchor=self.data['anchor']
        if not anchor or anchor['status'] not in {'recognized','at_recorded_waypoint'}:return
        place=next((p for p in self.data['places'] if p['ref']==anchor['place']),None)
        current=observation.get('location')
        if place and current and place.get('location') and current!=place['location']:
            anchor['status']='last_seen_not_current'
            self.persist()

    def route(self):
        return {'anchor': self.data['anchor'], 'steps': self.data['route'][-15:]}
