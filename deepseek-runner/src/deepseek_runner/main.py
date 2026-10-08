import argparse
import os
import sys
from pathlib import Path

from .bridge import BridgeFailure
from .client import DeepSeek, APIError
from .journal import Journal
from .runner import Runner


def main():
    parser=argparse.ArgumentParser(description='Direct DeepSeek 4.1 Flash (max) gameplay through AstraBridge native tools.')
    parser.add_argument('--skill',type=Path,required=True,help='Skill exported with --interface tools')
    parser.add_argument('--log-dir',type=Path,default=Path('deepseek-sessions'),help='Parent directory for full private session logs')
    parser.add_argument('--base-url',default='https://api.deepseek.com')
    parser.add_argument('--model',default='deepseek-flash')
    parser.add_argument('--astra',help='Explicit host executable override; never model-controlled')
    parser.add_argument('--task',help='Initial user goal; continue interactively afterwards')
    args=parser.parse_args()
    key=os.environ.get('DEEPSEEK_API_KEY')
    if not key:parser.error('Set DEEPSEEK_API_KEY in the environment. Do not put it in command arguments or source files.')
    journal=Journal(args.log_dir,key);api=None;runner=None
    print('Session log:',journal.root)
    try:
        api=DeepSeek(key,journal,args.base_url,args.model)
        runner=Runner(args.skill,journal,api,args.astra);context=runner.prepare()
        print('Connected profile:',context['profile']['name']);print('Enter a goal. /quit or EOF ends the connection.')
        text=args.task
        while not runner.stopped:
            if text is None:text=input('Task> ')
            if text.strip()=='/quit':break
            if text.strip():runner.turn(text)
            text=None
    except (EOFError,KeyboardInterrupt):
        print('\nEnding the agent connection.')
    except Exception as exc:
        journal.event('runner_error',error=str(exc));print(journal.clean(str(exc)),file=sys.stderr);return 1
    finally:
        if runner:runner.close()
        else:
            if api:api.close()
            journal.close()
    return 0


if __name__=='__main__':sys.exit(main())
