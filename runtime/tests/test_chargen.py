from astra_bridge.feedback import feedback
from astra_bridge.protocol import check_result


def test_chargen_list_selection_is_observed_and_keeps_only_ui_fields():
    a={'ui':{'elements':[{'role':'list_item','text':'Race A','selected':False}]}}
    b={'ui':{'elements':[{'role':'list_item','text':'Race A','selected':True}]}}
    check_result(b)
    r=feedback('choose',{'submitted':True},a,b)
    assert r['status']=='observed_change'
    assert {'kind':'list_selection_changed','selected':['Race A']} in r['events']


def test_repeating_tutorial_speech_is_one_event_per_action():
    a={'messages':[]}
    b={'messages':[{'text':'Follow me','frame':1},{'text':'Follow me','frame':2},{'text':'Look up','frame':3}]}
    r=feedback('act',{'reason':'duration'},a,b)
    speech=[e['text'] for e in r['events'] if e['kind']=='game_message']
    assert speech==['Follow me','Look up']
