"""Reacquire a previously used door from fresh visible geometry only."""
import math


def observed_anchor(row, pose, heading):
    distance = row.get('horizontal_distance_m')
    if distance is None or 'height_change_m' not in row:
        return None
    if 'center_bearing_deg' not in row:
        return None
    yaw = math.radians(heading + row['center_bearing_deg'])
    return [pose[0] + math.sin(yaw)*distance, pose[1] + math.cos(yaw)*distance,
            pose[2] + row['height_change_m']]


def match_door(rows, door, pose, heading):
    anchor = door.get('anchor')
    matches = [r for r in rows if r.get('kind') == 'door' and (anchor or (door.get('name')
               and r.get('name') == door['name'] and (not door.get('description')
               or r.get('description') == door['description'])))]
    if anchor:
        scored = []
        for row in matches:
            actual = observed_anchor(row, pose, heading)
            if actual is None or abs(actual[2] - anchor[2]) > 1.25:
                continue
            gap = math.dist(actual, anchor)
            if gap <= 1.5: scored.append((gap, row))
        scored.sort(key=lambda x:x[0])
        if scored and (len(scored) == 1 or scored[1][0] - scored[0][0] > .6):
            return scored[0][1], 'geometry'
        return None, 'door_ambiguous' if len(scored)>1 else 'known_door_not_visible'
    if len(matches) == 1: return matches[0], 'unique_caption'
    return None, 'door_ambiguous' if matches else 'known_door_not_visible'


def reacquire(session, step, budget):
    door = step['door']; elapsed = 0.; reason = 'known_door_not_visible'
    observation = session.latest_observation
    initial = observation.get('orientation',{}).get('heading_deg',0)
    heading = door.get('heading_deg', initial)
    anchor = door.get('anchor')
    pose = session.atlas.current()['pose']
    pitch = 0
    if anchor:
        d = [a-b for a,b in zip(anchor,pose)]
        heading = math.degrees(math.atan2(d[0],d[1])) % 360
        # Observed target center relative to approximate eye height; refine from visibility.
        pitch = max(-60,min(60,-math.degrees(math.atan2(d[2]-1.6,math.hypot(*d[:2])))))
    for offset in (None, 0, -35, 35, -70, 70):
        if session.control.cancelled.is_set(): return None, elapsed, 'cancelled'
        if offset is not None:
            if budget-elapsed<.5: return None, elapsed, 'step_limit'
            r=session.call('look',{'heading_deg':(heading+offset)%360,'pitch_deg':pitch})
            elapsed+=r['action'].get('elapsed',0);observation=r['observation']
            if r['action'].get('reason') in {'player_hurt','health_low','cancelled','location_changed'}:
                return None,elapsed,r['action']['reason']
        row,reason=match_door(observation.get('scene',{}).get('objects',[]),door,
                              session.atlas.current()['pose'],observation.get('orientation',{}).get('heading_deg',0))
        if row:return row,elapsed,reason
    return None,elapsed,reason
