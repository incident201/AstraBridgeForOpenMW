"""A map of travelled paths and observed local probes, never a level-map reader."""
from __future__ import annotations

from html import escape
from copy import deepcopy
import hashlib
import json
import math
import heapq
from pathlib import Path
import shutil
import subprocess
import sqlite3
import uuid
from .atlas_routes import AtlasRoutes


def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])


def bearing(a, b):
    return math.degrees(math.atan2(b[0]-a[0], b[1]-a[1])) % 360


class ExplorationAtlas(AtlasRoutes):
    def __init__(self, path: Path):
        self.path = path
        # SQLite is the durable authority. Legacy JSON remains untouched for recovery.
        self.db = sqlite3.connect(path.with_suffix('.sqlite3'), check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS graphs (ref TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS transitions (key TEXT PRIMARY KEY, profile TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS route_outcomes (id INTEGER PRIMARY KEY, profile TEXT NOT NULL, payload TEXT NOT NULL);
        """)
        self.data = {'segments': [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM graphs')], 'markers': []}
        self.profile = self._meta('profile') or uuid.uuid4().hex
        self._set_meta('profile', self.profile)
        if not self._meta('legacy_imported'):
            if path.exists():
                self.data = json.loads(path.read_text())
                for graph in self.data['segments']:
                    self._store(graph)
            self._set_meta('legacy_imported', '1')
        if not self._meta('checkpoints_imported'):
            for checkpoint in (path.parent / 'exploration-checkpoints').glob('*.json'):
                snapshot = json.loads(checkpoint.read_text())
                if snapshot.get('version') != 1: continue
                snapshot.setdefault('profile', self.profile)
                graph = snapshot['segment']
                if not any(s['ref'] == graph['ref'] for s in self.data['segments']):
                    graph['legacy_snapshot'] = snapshot['save']['description']
                    self.data['segments'].append(graph)
                    self._store(graph)
                self.db.execute('INSERT OR IGNORE INTO checkpoints VALUES (?,?)',
                                (self.save_key(snapshot['save']), json.dumps(snapshot, ensure_ascii=False)))
            self._set_meta('checkpoints_imported', '1')
        for graph in self.data['segments']:
            if 'profile' not in graph: self._store(graph)
        self.db.commit()
        self.visit = None
        self.active_offset = [0, 0, 0]
        self.segment = None
        self.sequence = 0
        self.restore_pending = None
        self._route_cache = None
        self.clock_epoch = uuid.uuid4().hex
        self.simulation_seconds = None

    def _meta(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, value))

    def _store(self, graph):
        graph.setdefault('profile', self.profile)
        self.db.execute('INSERT OR REPLACE INTO graphs VALUES (?,?)',
                        (graph['ref'], json.dumps(graph, ensure_ascii=False, separators=(',', ':'))))

    def new_game(self):
        self.reset_runtime()
        self.profile = uuid.uuid4().hex
        self._set_meta('profile', self.profile)
        self.db.commit()

    @staticmethod
    def save_key(slot):
        # Public save-list metadata; never parse game state from the save file.
        identity = slot.get('checkpoint_key') or [slot.get(k) for k in ('created', 'description', 'player_name', 'player_level')]
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()

    def checkpoint(self, slot):
        s = self.current()
        if not s or 'pose' not in s: return
        directory = self.path.parent / 'exploration-checkpoints'
        directory.mkdir(exist_ok=True)
        path = directory / (self.save_key(slot)+'.json')
        snapshot = {'version': 1, 'save': slot, 'segment': s, 'profile': self.profile}
        with self.db:
            player = slot.get('player_name', '')
            self._set_meta('player:' + player, self.profile)
            self._set_meta('owner:' + self.profile, player)
            self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?)',
                            (self.save_key(slot), json.dumps(snapshot, ensure_ascii=False)))
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')))
        tmp.replace(path)

    def restore(self, slot):
        self.reset_runtime()
        if not slot: return
        player = slot.get('player_name', '')
        known = self._meta('player:' + player)
        owner = self._meta('owner:' + self.profile)
        if known: self.profile = known
        elif owner and owner != player: self.profile = uuid.uuid4().hex
        self._set_meta('player:' + player, self.profile)
        self._set_meta('owner:' + self.profile, player)
        self._set_meta('profile', self.profile)
        self.db.commit()
        path = self.path.parent / 'exploration-checkpoints' / (self.save_key(slot)+'.json')
        row = self.db.execute('SELECT payload FROM checkpoints WHERE key=?', (self.save_key(slot),)).fetchone()
        if row or path.exists():
            snapshot = json.loads(row[0] if row else path.read_text())
            saved = snapshot.get('save', {})
            same_metadata = all(saved.get(k) == slot.get(k) for k in ('description','player_name','player_level'))
            if 'time_played_seconds' in saved and 'time_played_seconds' in slot:
                close_timestamp = saved['time_played_seconds'] == slot['time_played_seconds']
            else:
                close_timestamp = abs(saved.get('created',0)-slot.get('created',0)) < 1
            if snapshot.get('version') == 1 and same_metadata and close_timestamp:
                self.restore_pending = snapshot
                if snapshot.get('profile'):
                    self.profile = snapshot['profile']
                    self._set_meta('profile', self.profile)
                    self._set_meta('player:' + player, self.profile)
                    self._set_meta('owner:' + self.profile, player)
                    self.db.commit()

    def persist(self):
        with self.db:
            if self.current(): self._store(self.current())

    def reset_runtime(self):
        self.segment, self.sequence = None, 0
        self.visit = None
        self.restore_pending = None
        self.data['markers'] = []
        self.clock_epoch = uuid.uuid4().hex
        self.simulation_seconds = None

    def current(self):
        return next((s for s in self.data['segments'] if s['ref'] == self.segment), None)

    def ingest(self, observation, frame=None):
        clock = observation.get('simulation_seconds')
        if isinstance(clock, (int, float)) and math.isfinite(clock):
            if self.simulation_seconds is not None and clock < self.simulation_seconds - .01:
                self.clock_epoch = uuid.uuid4().hex
            self.simulation_seconds = clock
        if frame is not None:
            return self._ingest_anchored(observation, frame)
        return self._ingest_legacy(observation)

    def _ingest_anchored(self, observation, frame):
        """Private frame uses only the player's origin; never geometry or other objects.

        Exposed nodes remain relative to the current player. A cell transition,
        load or teleport starts a new stroke, never an edge through unseen space.
        """
        trace = observation.get('trajectory')
        if not trace or not trace.get('samples') and trace['ref'] != self.visit:
            return
        if trace['ref'] != self.visit:
            self.visit, self.sequence = trace['ref'], 0
            digest = hashlib.sha256((self.profile + '\0' + frame['space']).encode()).hexdigest()[:24]
            self.segment = 'space_' + digest
            s = self.current()
            snapshot, self.restore_pending = self.restore_pending, None
            if not s:
                # Only a verified save supplies a transform for a legacy graph.
                if snapshot and snapshot['segment']['location'] == observation.get('location'):
                    s = deepcopy(snapshot['segment'])
                    s['restored_from_save'] = snapshot['save']['description']
                    s['anchor'] = [a-b for a,b in zip(frame['origin'], s['pose'])]
                    for node in s['nodes']:
                        node['ref'] = f"node_{self.segment}_{node['label']}"
                        node.pop('motor_ref', None)
                else:
                    s = {'points': [], 'nodes': [], 'anchor': list(frame['origin'])}
                s.update(ref=self.segment, profile=self.profile, persistent=True, current_node=None,
                         location=observation.get('location', ''))
                s.pop('origin_offset', None)
                self.data['segments'].append(s)
            self.active_offset = [a-b for a,b in zip(frame['origin'], s['anchor'])]
            s['current_node'] = None
        s = self.current()
        angle = math.radians(trace['start_heading_deg'])
        for row in trace['samples']:
            if row['sequence'] <= self.sequence: continue
            f, r = row['forward_m'], row['sideways_m']
            point = [f*math.sin(angle)+r*math.cos(angle), f*math.cos(angle)-r*math.sin(angle), row['vertical_m']]
            point = [round(x+y, 4) for x,y in zip(point, self.active_offset)]
            gap = self.sequence == 0 or row['sequence'] != self.sequence+1
            s['points'].append({'p': point, 'sequence': row['sequence'], 'gap': gap})
            s['pose'], s['heading'] = point, row['heading_deg']
            self.sequence = row['sequence']
        s['location'] = observation.get('location', s['location'])
        s['locations'] = sorted(set(s.get('locations', []) + [s['location']]))
        self.persist()

    def catalog(self):
        return [{'ref': s['ref'], 'location': s['location'], 'locations':s.get('locations', [s['location']]), 'nodes': len(s['nodes']),
                 'recorded_points': len(s['points']), 'current': s['ref'] == self.segment,
                 'persistent': s.get('persistent', False)}
                for s in self.data['segments'] if s.get('profile', self.profile) == self.profile]

    def _ingest_legacy(self, observation):
        trace = observation.get('trajectory')
        if not trace or not trace.get('samples') and trace['ref'] != self.segment:
            return
        if trace['ref'] != self.segment:
            self.segment, self.sequence = trace['ref'], 0
            snapshot, self.restore_pending = self.restore_pending, None
            if snapshot and snapshot['segment']['location'] == observation.get('location'):
                restored = deepcopy(snapshot['segment'])
                restored['ref'] = self.segment
                restored['origin_offset'] = list(restored['pose'])
                restored['restored_from_save'] = snapshot['save']['description']
                refs = {}
                for node in restored['nodes']:
                    old_ref = node['ref']
                    node['ref'] = f"node_{self.segment}_{node['label']}"
                    refs[old_ref] = node['ref']
                    node['restored'] = bool(node.get('walkable') or node.get('motor_ref') or node.get('restored'))
                    node.pop('motor_ref', None)
                restored['current_node'] = refs.get(restored.get('current_node'))
                self.data['segments'] = [s for s in self.data['segments'] if s['ref'] != self.segment]
                self.data['segments'].append(restored)
            if not self.current():
                self.data['segments'].append({'ref': self.segment, 'points': [], 'nodes': [],
                                             'current_node': None, 'location': observation.get('location', '')})
            self.visit = self.segment
        s = self.current()
        angle = math.radians(trace['start_heading_deg'])
        for row in trace['samples']:
            if row['sequence'] <= self.sequence:
                continue
            f, r = row['forward_m'], row['sideways_m']
            point = [f*math.sin(angle)+r*math.cos(angle), f*math.cos(angle)-r*math.sin(angle), row['vertical_m']]
            point = [x+y for x,y in zip(point, s.get('origin_offset', [0,0,0]))]
            gap = self.sequence > 0 and row['sequence'] != self.sequence+1
            s['points'].append({'p': point, 'sequence': row['sequence'], 'gap': gap})
            s['pose'], s['heading'] = point, row['heading_deg']
            self.sequence = row['sequence']
        if s['points']:
            s['points'][0]['gap'] = True
        s['location'] = observation.get('location', s['location'])
        s['locations'] = sorted(set(s.get('locations', []) + [s['location']]))
        self.persist()

    def note_marker(self, ref):
        self.data['markers'].append(ref)
        self.data['markers'] = self.data['markers'][-64:]
        active = set(self.data['markers'])
        for s in self.data['segments']:
            for node in s['nodes']:
                if node.get('motor_ref') not in active:
                    node.pop('motor_ref', None)

    def annotate(self, observation):
        """Returns a new node that needs a private motor marker, or None."""
        s = self.current()
        body = observation.get('body', {})
        if not s or 'pose' not in s or observation.get('ui_mode') != 'Gameplay' or not body.get('on_ground') or body.get('swimming') or body.get('dead'):
            return None
        pose = s['pose']
        nearby = [n for n in s['nodes'] if distance(n['p'], pose) < 1.5 and abs(n['p'][2]-pose[2]) < .75]
        node = min(nearby, key=lambda n: distance(n['p'], pose)) if nearby else None
        created = False
        if node is None and (not s['nodes'] or distance(s['nodes'][-1]['p'], pose) >= 3
                             or abs(s['nodes'][-1]['p'][2]-pose[2]) >= 1):
            index = s.get('node_serial', 0)+1
            s['node_serial'] = index
            node = {'ref': f"node_{self.segment}_{index}", 'label': f'A{index}', 'p': list(pose),
                    'visits': 0, 'views': [], 'probes': [], 'options': [], 'walkable': True}
            s['nodes'].append(node)
            created = True
        if node is None:
            s['current_node'] = None
            return None
        if s.get('current_node') != node['ref']:
            node['visits'] += 1
            history=s.setdefault('visit_history',[])
            s['loop_detected']=any(v['ref']==node['ref'] and v['nodes']==len(s['nodes']) for v in history)
            s['visit_history']=(history+[{'ref':node['ref'],'nodes':len(s['nodes'])}])[-20:]
        s['current_node'] = node['ref']
        node['location'] = observation.get('location',s['location'])
        if observation.get('screenshot'): node['views'] = (node['views']+[observation['screenshot']])[-3:]
        landmarks = [o.get('description') or o['name'] for o in observation.get('scene', {}).get('objects', [])
                     if o['kind'] == 'door' and o['distance_m'] < 10]
        node['landmarks'] = sorted(set(node.get('landmarks', []) + landmarks))
        terrain = observation.get('terrain', {})
        if terrain.get('supported'):
            # Probes are observations at this pose, not a filled polygon between rays.
            rays = []
            for ray in terrain.get('rays', []):
                angle = math.radians(s['heading']+ray['bearing_deg'])
                end = [pose[0]+math.sin(angle)*ray['clear_m'], pose[1]+math.cos(angle)*ray['clear_m'],
                       pose[2]+ray['height_change_m']]
                rays.append({'a': list(pose), 'b': end, 'status': ray['status']})
            node['probes'] = rays
            node['option_origin'] = list(pose)
            node['options'] = [{'heading': (s['heading']+p['bearing_deg']) % 360,
                                'meters': p['distance_m'], 'height': p['height_change_m']} for p in terrain.get('passages', [])]
        self.persist()
        return node if created or not node.get('motor_ref') else None

    def untraversed(self, node):
        """Directions not crossed by any recorded path near this observation."""
        s = self.current()
        remaining = []
        origin = node.get('option_origin', node['p'])
        local = [(row['p'], distance(origin, row['p'])) for row in s['points']
                 if abs(row['p'][2]-origin[2]) < 1.5]
        local = [(p, d) for p, d in local if .8 <= d <= 3]
        for option in node['options']:
            travelled = False
            for point, d in local:
                if d <= min(3, option['meters']+.5):
                    delta = (bearing(origin, point)-option['heading']+180) % 360-180
                    if abs(delta) < 25:
                        travelled = True
                        break
            if not travelled:
                remaining.append(option)
        return remaining

    def resolve(self, ref):
        s = self.current()
        if not s:
            return None
        matches = [n for n in s['nodes'] if n['ref'] == ref or n['label'] == ref]
        return matches[0] if len(matches) == 1 else None

    def travelled_routes(self, start=None, space=None):
        """Shortest routes along this branch's actual samples, including their Z.

        Only consecutive samples and repeat visits to the same small foot pose
        connect. Nearby map nodes, probes, and missing samples never create edges.
        The motor still collision-checks each segment against the current world.
        """
        s = space or self.current()
        if not s or not s.get('points'):
            return {}, [], []
        origin = start if start is not None else s['pose']
        cache_key = (s['ref'], len(s['points']), len(s['nodes']), tuple(origin))
        if self._route_cache and self._route_cache[0] == cache_key: return self._route_cache[1]
        points = [row['p'] for row in s['points']]
        edges = [[] for _ in points]
        buckets = {}
        reachable_nodes = s['nodes']
        def connect(i, j):
            d = math.dist(points[i], points[j])
            edges[i].append((j, d))
            edges[j].append((i, d))
        for i, row in enumerate(s['points']):
            p = row['p']
            if i and not row['gap']:
                # Do not turn a recorded fall, teleport or large sampling gap
                # into an instruction to walk back up it.
                prev = points[i-1]
                if math.dist(prev, p) < 2 and abs(prev[2]-p[2]) <= distance(prev, p)*1.1+.15:
                    connect(i-1, i)
            key = tuple(math.floor(v/.075) for v in p)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for j in buckets.get((key[0]+dx, key[1]+dy, key[2]+dz), ()):
                            if math.dist(points[j], p) <= .075:
                                connect(i, j)
            buckets.setdefault(key, []).append(i)
        candidates=[i for i,p in enumerate(points) if math.dist(p,origin)<.04]
        if not candidates:return {},[],points
        start = min(candidates,key=lambda i:math.dist(points[i],origin))
        costs, parents = {start: 0.0}, {start: None}
        queue = [(0.0, start)]
        while queue:
            cost, i = heapq.heappop(queue)
            if cost != costs[i]:
                continue
            for j, length in edges[i]:
                candidate = cost+max(length, .00001)
                if candidate < costs.get(j, math.inf):
                    costs[j], parents[j] = candidate, i
                    heapq.heappush(queue, (candidate, j))
        routes = {}
        for n in reachable_nodes:
            key = tuple(math.floor(v/.075) for v in n['p'])
            candidates = (i for dx in (-1,0,1) for dy in (-1,0,1) for dz in (-1,0,1)
                          for i in buckets.get((key[0]+dx,key[1]+dy,key[2]+dz), ()))
            matches = [i for i in candidates if i in costs and math.dist(points[i], n['p']) <= .04]
            if matches:
                end = min(matches, key=lambda i: costs[i]+math.dist(points[i], n['p']))
                routes[n['ref']] = (end, costs[end]+math.dist(points[end], n['p']))
        result = routes, parents, points
        self._route_cache = (cache_key, result)
        return result

    def travelled_route(self, node):
        routes, parents, points = self.travelled_routes()
        if node['ref'] not in routes:
            return None
        index = routes[node['ref']][0]
        route = [list(node['p'])]
        while index is not None:
            if math.dist(route[-1], points[index]) > .025:
                route.append(points[index])
            index = parents[index]
        route.reverse()
        # Keep recorded corners and height changes. Remove only points lying
        # within 3 cm of the next segment, with a bounded one metre segment.
        reduced = []
        for p in route:
            while len(reduced) >= 2:
                a, b = reduced[-2:]
                d = [y-x for x,y in zip(a,p)]
                length2 = sum(v*v for v in d)
                t = sum((x-y)*v for x,y,v in zip(b,a,d))/length2 if length2 else 0
                closest = [x+max(0,min(1,t))*v for x,v in zip(a,d)]
                if length2 > 1 or math.dist(b, closest) > .03:
                    break
                reduced.pop()
            reduced.append(p)
        return reduced

    def summary(self):
        s=self.current()
        if not s:return {'supported':False}
        return {'supported':True,'segment':s['ref'],'current_node':s.get('current_node'),
                'persistent':s.get('persistent',False),'loop_detected':s.get('loop_detected',False)}

    def present(self, path: Path | None, radius=35, archived=False, page=0, limit=20, level=None):
        s = self.current()
        if not s or 'pose' not in s:
            return {'supported': False}
        pose = s['pose']
        levels=self.level_rows(s)
        level_ids={l['ref'] for l in levels if l['ref']==level or l['label']==level} if level else None
        nodes = sorted([n for n in s['nodes'] if distance(n['p'], pose) <= radius],
                       key=lambda n: (abs(n['p'][2]-pose[2])>1.25,distance(n['p'], pose)))
        if level_ids is not None:nodes=[n for n in nodes if n.get('level') in level_ids]
        total=len(nodes);nodes=nodes[page*limit:(page+1)*limit]
        rows = []
        routes, _, _ = self.travelled_routes()
        for n in nodes:
            directions = self.untraversed(n)
            relative_bearing = (bearing(pose, n['p'])-s['heading']+180) % 360-180 if distance(n['p'],pose)>.05 else 0
            rows.append({'ref': n['ref'], 'label': n['label'], 'names':n.get('names',[]),'level':n.get('level'),
                         'location':n.get('location',s['location']), 'distance_m': round(distance(n['p'], pose), 2),
                         'bearing_deg': round(relative_bearing, 1),
                         'height_change_m': round(n['p'][2]-pose[2], 2), 'visits': n['visits'],
                         'can_revisit': n['ref'] in routes or bool(s.get('persistent') and n.get('walkable') and math.dist(n['p'], pose) < 100),
                         'revisit_source': 'recorded_trail' if n['ref'] in routes else 'native_path_required' if s.get('persistent') and n.get('walkable') and math.dist(n['p'], pose) < 100 else 'unavailable',
                         'route_distance_m': round(routes[n['ref']][1], 2) if n['ref'] in routes else None,
                         'untraversed_directions': [{'heading_deg': round(d['heading'], 1), 'meters': d['meters']} for d in directions],
                         'landmarks': n.get('landmarks', []), 'screenshots': [self.portable_view(v) for v in n['views'] if v and Path(v).is_file()]})
        if archived:
            for row in rows:
                row['can_revisit'] = False
                row['revisit_source'] = 'different_space'
        if path: self.render(path, radius, nodes, rows)
        result = {'supported': True, 'segment': self.segment, 'source': 'travelled_path_and_observed_probes',
                  'location': s['location'], 'radius_m': radius, 'nodes': rows,
                  'persistent': s.get('persistent', False), 'spaces': self.catalog(), 'archived':archived,
                  'not_a_full_map': True, 'sampled_path': True,
                  'recorded_points': len(s['points']), 'current_node': s.get('current_node')}
        result.update(levels=levels,page=page,limit=limit,total=total,has_more=(page+1)*limit<total,
                      loop_detected=s.get('loop_detected',False),transitions=self.transitions())
        self.persist()
        if s.get('restored_from_save'): result['restored_from_save'] = s['restored_from_save']
        if path: result['svg'] = str(path)
        converter = shutil.which('rsvg-convert') if path else None
        if converter:
            png = path.with_suffix('.png')
            completed = subprocess.run([converter, '-o', str(png), str(path)], capture_output=True, timeout=5)
            if completed.returncode == 0:
                result['png'] = str(png)
        return result

    def portable_view(self, value):
        if not value or Path(value).exists(): return value
        local = self.path.parent / 'screenshots' / Path(value).name
        return str(local) if local.exists() else value

    def render(self, path, radius, nodes, public):
        s = self.current(); pose = s['pose']; scale = 650/(radius*2)
        def point(p): return 360+(p[0]-pose[0])*scale, 370-(p[1]-pose[1])*scale
        def xy(p):
            x, y = point(p); return f'{x:.1f},{y:.1f}'
        svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="740" viewBox="0 0 1100 740">',
               '<rect width="1100" height="740" fill="#101923"/>',
               '<defs><clipPath id="map"><rect x="20" y="50" width="680" height="645"/></clipPath></defs>',
               '<g font-family="DejaVu Sans,sans-serif" font-size="13" fill="#d6e3ed">',
               f'<text x="20" y="28">Travel memory · {escape(s["location"])} · North is up</text>',
               '<g clip-path="url(#map)">']
        for metres in range(5, int(radius)+1, 5):
            svg.append(f'<circle cx="360" cy="370" r="{metres*scale:.1f}" fill="none" stroke="#253545"/>')
            svg.append(f'<text x="365" y="{370-metres*scale+14:.1f}" fill="#657c8d">{metres} m</text>')
        for n in nodes:
            for ray in n['probes']:
                if abs(ray['a'][2]-pose[2]) > 1.5: continue
                svg.append(f'<polyline points="{xy(ray["a"])} {xy(ray["b"])}" fill="none" stroke="#587768" opacity=".24"/>')
        previous = None
        for row in s['points']:
            p = row['p']
            if previous is not None and not row['gap'] and min(distance(previous, pose), distance(p, pose)) <= radius:
                color = '#5bd5ea' if abs(p[2]-pose[2]) < 1.5 else '#6c7286'
                svg.append(f'<polyline points="{xy(previous)} {xy(p)}" fill="none" stroke="{color}" stroke-width="2"/>')
            previous = p
        for n, row in zip(nodes, public):
            x, y = point(n['p'])
            other_floor = abs(row['height_change_m']) > 1.5
            color = '#8b95aa' if other_floor else '#ffc777' if row['untraversed_directions'] else '#b6ced8'
            fill = '#101923' if other_floor else color
            label = n['label'] + (f" ({row['height_change_m']:+.1f}m)" if other_floor else '')
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{fill}" stroke="{color}"/>')
            svg.append(f'<text x="{x+7:.1f}" y="{y-6:.1f}" fill="{color}">{escape(label)}</text>')
            for option in row['untraversed_directions']:
                angle = math.radians(option['heading_deg']); length = min(2, option['meters'])*scale
                ox, oy = point(n.get('option_origin', n['p']))
                svg.append(f'<path d="M {ox:.1f},{oy:.1f} l {math.sin(angle)*length:.1f},{-math.cos(angle)*length:.1f}" stroke="#ffc777" stroke-dasharray="3 3"/>')
        svg.extend(['</g>', f'<g transform="translate(360 370) rotate({s["heading"]:.2f})"><path d="M 0,-14 L -8,9 L 0,5 L 8,9 Z" fill="white" stroke="#101923"/></g>',
                    '<text x="710" y="55">Visited observations</text>'])
        for i, row in enumerate(public[:16]):
            y = 83+i*35
            label = f"{row['label']} · {row['distance_m']:.1f} m · height {row['height_change_m']:+.1f} · visits {row['visits']}"
            svg.append(f'<text x="710" y="{y}">{escape(label)}</text>')
            detail = f"Recorded route: {row['route_distance_m']:.1f} m" if row['route_distance_m'] is not None else 'Requires current native path' if row['can_revisit'] else 'No connected recorded route'
            svg.append(f'<text x="720" y="{y+16}" fill="#92a4b4" font-size="11">{escape(detail)}</text>')
        svg.extend(['<text x="20" y="716">Cyan: sampled path · grey: other height · green: observed rays · dashed: directions not traversed</text>',
                    '<text x="710" y="685" fill="#92a4b4">No surface is inferred between rays.</text>',
                    '</g></svg>'])
        path.write_text('\n'.join(svg), encoding='utf-8')
