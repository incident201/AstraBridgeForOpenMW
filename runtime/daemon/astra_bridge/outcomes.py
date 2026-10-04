"""Small outcome summaries derived from measured motion and existing diagnostics."""
import math


TIME_LIMITS = {'step_limit','sequence_time_limit','wall_time_limit','condition_timeout','turn_limit','chain_time_limit'}
STALLED = {'blocked','no_route_progress','repeated_positions','repeated_obstruction','no_progress',
           'no_horizontal_progress','no_observed_movement','maneuver_blocked'}
NO_HORIZONTAL_PROGRESS = {'no_horizontal_progress','no_observed_movement'}
DESTINATIONS = {'go','walk','move_local','fly','swim','revisit','return_to'}
_UNSET = object()


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def changed_location(action):
    changed=action.get('motion',{}).get('location_changed')
    if (changed is True or action.get('outcome')=='location_changed'
            or action.get('reason') in {'location_changed','unexpected_location'}):return True
    # Adjacent exterior areas can have different labels in one continuous frame.
    if changed is False:return False
    return action.get('changes',{}).get('location_changed') is True


def horizontal_displacement(action):
    if changed_location(action):return None
    motion=action.get('motion',{})
    forward,side=motion.get('forward_m'),motion.get('sideways_m')
    if finite(forward) and finite(side):return round(math.hypot(forward,side),2)
    # A measured zero 3D displacement also proves zero horizontal displacement.
    # A positive 3D value, or absent motion, cannot establish horizontal progress.
    if finite(motion.get('moved_m')) and motion['moved_m']==0:return 0.0
    return None


def no_horizontal_progress(op, action, inputs):
    if op=='act':requested=bool(inputs.get('move') or inputs.get('strafe'));default=.25
    elif op in {'jump','air_move'}:requested=inputs.get('direction','none')!='none';default=8 if op=='jump' else .5
    else:return False
    if not requested or action.get('reason') not in {'duration','landed'}:return False
    seconds=inputs.get('seconds',default)
    elapsed=action.get('elapsed',seconds)
    # Short inputs can finish before acceleration or one physics update is visible.
    if not finite(seconds) or not finite(elapsed) or min(seconds,elapsed)<.2:return False
    distance=horizontal_displacement(action)
    return distance is not None and distance<.05


def _position(session):
    atlas=getattr(session,'atlas',None)
    graph=atlas.current() if atlas else None
    if not graph:return None
    pose=graph.get('pose')
    if not isinstance(pose,(list,tuple)) or len(pose)!=3 or not all(finite(v) for v in pose):return None
    # The controller already retains the player's observed position for the Atlas.
    # Only the final scalar distance is public, never these private coordinates.
    frame=(getattr(atlas,'profile',None),graph['ref'],tuple(graph.get('anchor',graph.get('origin_offset',[]))),
           getattr(atlas,'visit',None),getattr(atlas,'clock_epoch',None))
    return frame,tuple(pose[:2])


class MotionSpan:
    """Endpoint displacement in one unchanged Atlas frame; not distance travelled."""
    def __init__(self,session=None):
        self.initialized=session is not None
        self.start=_position(session)
        self.end=self.start
        self.comparable=self.start is not None

    def begin(self,session):
        if not self.initialized:self.__init__(session)
        else:self.sample(session)

    def sample(self,session,action=None):
        self.end=_position(session)
        if (action and changed_location(action) or self.start is None or self.end is None
                or self.start[0]!=self.end[0]):self.comparable=False

    def distance(self):
        if not self.comparable:return None
        return round(math.dist(self.start[1],self.end[1]),2)


def _diagnostics(action):
    existing=action.get('summary')
    if existing is not None:
        return set(existing['encountered_blockers']),existing['stalled_attempts'],set(existing['warnings'])
    blockers=set();warnings=set();stalled=0
    for navigation in (action,action.get('movement',{}),action.get('navigation',{}),action.get('feedback',{}).get('navigation',{}),
                       action.get('movement',{}).get('navigation',{})):
        blocker=(navigation or {}).get('blocked_by')
        if isinstance(blocker,str) and blocker:blockers.add(blocker)
    children=action.get('steps',[])
    for step in children:
        b,s,w=_diagnostics(step);blockers.update(b);stalled+=s;warnings.update(w)
    reason=action.get('feedback',{}).get('reason') or action.get('reason')
    if reason in NO_HORIZONTAL_PROGRESS:warnings.add('no_horizontal_progress')
    if 'attempts' in action:
        # A revisit retry can stop before a motor call; its attempt record is the
        # authority. Do not count that failure again through its nested go result.
        stalled=sum(attempt.get('reason') in STALLED for attempt in action['attempts'])
    elif not children:stalled=int(reason in STALLED)
    return blockers,stalled,warnings


def summarize(result, op, displacement=_UNSET):
    action=result.get('action',{});feedback=result.get('feedback',{})
    reason=feedback.get('reason') or action.get('reason')
    blockers,stalled,warnings=_diagnostics({**action,'feedback':feedback})
    summary={'status':feedback.get('status','observed'),'reason':reason,
             'termination':'time_limit' if reason in TIME_LIMITS else reason,
             'horizontal_displacement_m':horizontal_displacement(action) if displacement is _UNSET else displacement,
             'encountered_blockers':sorted(blockers),'stalled_attempts':stalled,'warnings':sorted(warnings)}
    if op in DESTINATIONS:summary['destination_reached']=action.get('reason')=='arrived'
    for key in ('elapsed','completed_actions','total_actions','stopped_step'):
        if key in action:summary[key]=action[key]
    result['summary']=summary
    return result


def step_result(result, operation):
    """Preserve child feedback and summaries instead of retaining only raw action."""
    return {'operation':operation,**result.get('action',{}),
            **{key:result[key] for key in ('feedback','summary') if key in result}}
