#!/usr/bin/env python3
"""Explicit GPU-host integration check against an installed test runtime."""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--save-description',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();cfg=json.loads(args.config.read_text());results={};agent=None
    def api(path,data=None,method=None):
        headers={'Authorization':'Bearer '+cfg['token'],'Content-Type':'application/json'}
        if agent:headers['X-Astra-Session']=agent
        req=urllib.request.Request(f'http://127.0.0.1:{cfg["apiPort"]}'+path,
            data=json.dumps(data).encode() if data is not None else None,method=method,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=120) as response:result=json.load(response)
        except urllib.error.HTTPError as exc:raise RuntimeError(exc.read().decode()) from exc
        if not result.get('ok'):raise RuntimeError(result)
        return result['result']
    def game(op,params):return api('/v1/game/command',{'op':op,'args':params})
    def action(yaw,seconds):return game('act',{'yaw':yaw,'seconds':seconds})
    try:
        api('/v1/runtime/engine/start',{})
        agent=api('/v1/agent/connect',{'name':'Explicit integration test'})['session_token']
        saves=game('saves',{})['saves'];matches=[s for s in saves if s['description']==args.save_description]
        if len(matches)!=1:raise ValueError('Select one unique test save description')
        game('load',{'ref':matches[0]['ref']})
        results['viewer720']=api('/v1/runtime/live',{'quality':'720p30'})
        print('720p30 live:',results['viewer720']['encoder']['encoder'],flush=True)
        results['record_start']=api('/v1/runtime/recording/start',{})
        print('Recording started',flush=True)
        results['action1']=action(60,2)
        results['viewer1080']=api('/v1/runtime/live',{'quality':'1080p60'})
        print('1080p60 live started',flush=True)
        results['action2']=action(-60,2)
        api('/v1/runtime/live',method='DELETE')
        results['action3']=action(20,1)
        results['viewer_restart']=api('/v1/runtime/live',{'quality':'720p30'})
        results['action4']=action(-20,1)
        before=api('/v1/runtime/status');time.sleep(3);after=api('/v1/runtime/status')
        results['paused_sample_delta']=after['media_samples']-before['media_samples']
        assert results['paused_sample_delta']==0,'Viewer advanced the benchmark clock during a thinking pause'
        results['record_stop']=api('/v1/runtime/recording/stop',{})
        print('Recording stopped; thinking pause sample delta: 0',flush=True)
        results['viewer_after_recording']=api('/v1/runtime/status')['viewer']
        assert results['viewer_after_recording']['running']
        results['action_after_recording']=action(0,.5)
        results['recordings']=api('/v1/runtime/recordings')
    finally:
        for path,method in (('/v1/runtime/live','DELETE'),('/v1/runtime/recording/stop','POST'),('/v1/agent/disconnect','POST')):
            try:api(path,{} if method=='POST' else None,method)
            except Exception:pass
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
