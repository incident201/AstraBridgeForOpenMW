"""Controller chunking must not impose a whole-journey range ceiling."""
import math
import threading
from types import SimpleNamespace

import pytest

from astra_bridge.workflows import navigate


class RouteSession:
    def __init__(self, distance, recorded):
        self.graph={'ref':'space_test','pose':[0.,0.,0.]}
        self.node={'ref':'node_test','p':[0.,distance,0.]}
        self.recorded=recorded
        self.markers=[]
        self.calls=[]
        self.control=SimpleNamespace(cancelled=threading.Event())
        self.atlas=SimpleNamespace(
            profile='profile',visit='visit',clock_epoch='clock',segment='space_test',
            current=lambda:self.graph,find_node=lambda _:(self.graph,self.node),
            route_to=lambda _: {'destination':'node_test','steps':[
                {'kind':'walk','ref':'node_test','source':'recorded_trail' if recorded else 'native_path_required'}]},
            travelled_route=self.route,record_outcome=lambda *args:None)

    def route(self, node):
        if not self.recorded:return None
        start=self.graph['pose'][1]
        return [[0.,y,0.] for y in range(math.floor(start)+1,math.floor(node['p'][1])+1)]

    def observe(self, **kwargs):
        return {'state':'running','ui_mode':'Gameplay','orientation':{'view_distance_m':5}}

    def command(self, op, **kwargs):
        assert op=='mark'
        self.markers.append(kwargs)
        self.goal=[a+b for a,b in zip(self.graph['pose'],kwargs['_atlas_offset'])]
        return {'ref':'waypoint_test'}

    def call(self, op, args):
        assert op=='go'
        self.calls.append(args)
        distance=math.dist(self.graph['pose'],self.goal)
        self.graph['pose']=self.goal[:]
        return {'action':{'reason':'arrived','elapsed':distance/10,
                          'motion':{'forward_m':distance,'sideways_m':0,'location_changed':False}},
                'feedback':{'status':'succeeded','reason':'arrived'},'observation':self.observe()}


def test_connected_journey_runs_all_chunks_beyond_view_distance():
    session=RouteSession(2000,recorded=True)
    result=navigate(session,{'ref':'node_test','seconds':300,'run':True})
    assert result['summary']['destination_reached']
    assert session.graph['pose']==[0.,2000.,0.]
    assert len(session.calls)>30
    assert all(math.dist([0,0,0],m['_atlas_offset'])<=60 for m in session.markers)
    assert all(0<len(m['_atlas_route'])<=400 for m in session.markers)
    assert result['action']['elapsed']==pytest.approx(200)
    assert session.calls[-1]['seconds']==pytest.approx(300-198)


def test_accepted_native_goal_is_not_rejected_at_100_metres():
    session=RouteSession(150,recorded=False)
    result=navigate(session,{'ref':'node_test','seconds':30})
    assert result['summary']['destination_reached']
    assert session.markers==[{'_atlas_offset':[0.,150.,0.],'_atlas_route':None}]
    assert len(session.calls)==1
