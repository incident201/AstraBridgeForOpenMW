import copy
import pytest
from astra_bridge.session import Session
from astra_bridge.protocol import BridgeError, validate

class ScanDriver:
    scan=Session.scan
    def __init__(self,interrupt=False,lock='unlocked'):
        self.current={'state':'running','paused':True,'ui_mode':'Gameplay',
                      'target_lock':{'status':lock},'orientation':{'heading_deg':350}}
        self.calls=[];self.interrupt=interrupt
    def observe(self):return copy.deepcopy(self.current)
    def call(self,op,args):
        if op=='look':
            old=self.current['orientation'].get('pitch_deg',0)
            self.current['orientation']['pitch_deg']=args['pitch_deg'];self.calls.append(args)
            return {'action':{'elapsed':abs(old-args['pitch_deg'])/120,'reason':'duration'},'observation':self.observe()}
        assert op=='act' and set(args)=={'yaw','seconds'}
        self.calls.append(args)
        self.current['orientation']['heading_deg']=(self.current['orientation']['heading_deg']+args['yaw'])%360
        if self.interrupt=='modal':self.current['ui']={'modal':True}
        elif self.interrupt:self.current['ui_mode']='Dialogue'
        return {'action':{'elapsed':abs(args['yaw'])/120,'reason':'ui_open' if self.interrupt and self.interrupt!='modal' else 'duration'},
                'observation':self.observe()}

def test_scan_turns_actor_in_one_direction_without_return():
    driver=ScanDriver();result=driver.scan()
    assert len(driver.calls)==3 and len(result['views'])==4
    assert all(c['yaw']==90 for c in driver.calls)
    assert result['elapsed']==2.25 and result['completed']
    assert result['final']['orientation']['heading_deg']==260
    with pytest.raises(BridgeError):validate('preview',{'yaw':90})

def test_scan_does_not_keep_turning_after_interruption_or_unlock_silently():
    driver=ScanDriver(interrupt=True);result=driver.scan()
    assert len(driver.calls)==1 and not result['completed']
    driver=ScanDriver(lock='locked')
    with pytest.raises(BridgeError,match='target_locked'):driver.scan()
    assert not driver.calls

def test_scan_levels_view_and_supports_an_explicit_vertical_band():
    driver=ScanDriver();driver.current['orientation']['pitch_deg']=-60
    result=driver.scan()
    assert driver.calls[0]=={'pitch_deg':0} and len(result['views'])==4
    assert all(v['observation']['orientation']['pitch_deg']==0 for v in result['views'])
    driver=ScanDriver();result=driver.scan(-35)
    assert all(v['observation']['orientation']['pitch_deg']==-35 for v in result['views'])


def test_scan_stops_on_modal_even_when_ui_mode_and_action_reason_look_normal():
    driver=ScanDriver(interrupt='modal');result=driver.scan()
    assert len(driver.calls)==1 and not result['completed'] and result['reason']=='ui_input_required'
    assert result['final']['ui']['modal']
    driver=ScanDriver();driver.current['ui']={'modal':True}
    with pytest.raises(BridgeError,match='ui_open'):driver.scan()
    assert not driver.calls


def test_scan_final_image_is_shared_only_when_that_view_was_completed():
    for interrupted in (False,True):
        driver=ScanDriver(interrupt=interrupted)
        frames=[]
        def observe():
            result=copy.deepcopy(driver.current)
            result['screenshot']=f'frame-{len(frames)}.png';frames.append(result)
            return result
        driver.observe=observe
        result=driver.scan()
        same=result['final']['screenshot']==result['views'][-1]['observation']['screenshot']
        assert same is not interrupted
