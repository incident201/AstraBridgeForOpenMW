"""Controller chunking must not impose a whole-journey range ceiling."""
import math
import threading
from types import SimpleNamespace

import pytest

from astra_bridge.workflows import navigate
from astra_bridge.exploration import ExplorationAtlas


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


def test_chunks_continue_forward_after_inexact_arrival(tmp_path):
    """Native shortcuts can stay outside the recorded trace's tiny join radius."""
    class SettledSession:
        def __init__(self):
            self.atlas=ExplorationAtlas(tmp_path/'atlas.json')
            self.control=SimpleNamespace(cancelled=threading.Event())
            self.sequence=0;self.markers=[];self.calls=[];self.distance=0
            self.feed([[0.,0.,0.]])
            self.destination=self.atlas.annotate(self.observe())['ref']
            self.feed([[0.,float(y),0.] for y in range(1,121)])
            self.atlas.annotate(self.observe())

        def feed(self, points):
            rows=[]
            for x,y,z in points:
                self.sequence+=1
                rows.append({'sequence':self.sequence,'forward_m':y,
                             'sideways_m':x,'vertical_m':z,'heading_deg':0})
            self.atlas.ingest({'state':'running','location':'Hall','ui_mode':'Gameplay',
                'body':{'on_ground':True},'trajectory':{'ref':'recorded_hall',
                    'sequence':self.sequence,'start_heading_deg':0,'samples':rows,'sparse':False}})

        def observe(self, **kwargs):
            return {'state':'running','location':'Hall','ui_mode':'Gameplay',
                    'body':{'on_ground':True},'orientation':{'view_distance_m':5}}

        def command(self, op, **kwargs):
            assert op=='mark'
            self.markers.append(kwargs)
            self.goal=[a+b for a,b in zip(self.atlas.current()['pose'],kwargs['_atlas_offset'])]
            return {'ref':'waypoint_test'}

        def call(self, op, args):
            assert op=='go'
            start=list(self.atlas.current()['pose'])
            # A normal native shortcut in an open corridor stops 28 cm from
            # its target. Its entire trace stays 20 cm beside the old trace;
            # rebuilding a graph route joins it only at the old departure.
            end=[self.goal[0]+.2,self.goal[1]+.2,self.goal[2]]
            distance=math.dist(start,end);self.distance+=distance
            count=max(1,math.ceil(distance*2))
            self.feed([[.2,start[1]+(end[1]-start[1])*i/count,end[2]]
                       for i in range(1,count+1)])
            self.calls.append(self.goal[:])
            return {'action':{'reason':'arrived','elapsed':distance/10,
                    'motion':{'forward_m':end[1]-start[1],'sideways_m':end[0]-start[0],
                              'location_changed':False}},
                    'feedback':{'status':'succeeded','reason':'arrived'},'observation':self.observe()}

    session=SettledSession()
    result=navigate(session,{'ref':session.destination,'seconds':40})
    assert result['summary']['destination_reached']
    assert session.distance<123,'chunk continuation must not return to the original departure'
    assert len(session.calls)==3
    assert all(b[1]<a[1] for a,b in zip(session.calls,session.calls[1:]))
    assert all(m['_atlas_route'][0]==[0,0,0] for m in session.markers)
    outcomes=session.atlas.route_outcomes()
    assert len(outcomes)==1 and outcomes[0]['success'], 'intermediate chunks must not claim final arrival'
