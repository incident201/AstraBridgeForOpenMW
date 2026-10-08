import argparse
import json
import os
import sys
from pathlib import Path

from .auth import AuthStore
from .journal import Journal
from .locking import FileLock
from .providers.deepseek import DeepSeek
from .providers.openai import OpenAI
from .runner import Runner


def parser():
    root = argparse.ArgumentParser(description='AstraBridge native-tool runner: ChatGPT OAuth or DeepSeek API.')
    root.add_argument('--auth-dir', type=Path, help='Protected ChatGPT credential directory')
    sub = root.add_subparsers(dest='command', required=True)
    auth = sub.add_parser('auth'); actions = auth.add_subparsers(dest='auth_action', required=True)
    login = actions.add_parser('login'); login.add_argument('--no-browser', action='store_true')
    login.add_argument('--callback-port', type=int); login.add_argument('--account'); login.add_argument('--new-account', action='store_true')
    actions.add_parser('status'); actions.add_parser('accounts')
    use = actions.add_parser('use'); use.add_argument('account')
    logout = actions.add_parser('logout'); logout.add_argument('--account')
    models = sub.add_parser('models'); models.add_argument('--provider', choices=('openai', 'deepseek'), required=True)
    models.add_argument('--account'); models.add_argument('--json', action='store_true')
    run = sub.add_parser('run'); run.add_argument('--provider', choices=('openai', 'deepseek'), required=True)
    run.add_argument('--model', required=True); run.add_argument('--reasoning', required=True)
    run.add_argument('--skill', type=Path, required=True); run.add_argument('--account')
    run.add_argument('--task'); run.add_argument('--log-dir', type=Path, default=Path('astrabridge-sessions'))
    run.add_argument('--context-window', type=int); run.add_argument('--image-context', type=int, choices=(1, 2), default=2)
    run.add_argument('--compaction', choices=('checkpoint', 'off'), default='checkpoint')
    run.add_argument('--compact-at', type=float, default=.75, help='Context fraction triggering compaction (default .75)')
    run.add_argument('--astra'); run.add_argument('--base-url', help='DeepSeek deployment override; OpenAI always uses the official OAuth route')
    resume = sub.add_parser('resume'); resume.add_argument('session', type=Path); resume.add_argument('--task')
    return root


def provider(name, journal, args, model, effort, account=None):
    if name == 'openai':
        auth=AuthStore(args.auth_dir,journal=journal)
        try:return OpenAI(auth,journal,model,effort,account=account)
        except BaseException:auth.close();raise
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key: raise ValueError('Set DEEPSEEK_API_KEY in the environment; do not put keys in arguments or prompts.')
    return DeepSeek(key, journal, getattr(args, 'base_url', None) or 'https://api.deepseek.com', model, effort)


def main(argv=None):
    arguments = parser(); args = arguments.parse_args(argv)
    if args.command == 'auth':
        auth = AuthStore(args.auth_dir)
        try:
            if args.auth_action == 'login':
                if args.callback_port is not None and not 1 <= args.callback_port <= 65535: raise ValueError('Callback port must be between 1 and 65535.')
                if args.new_account and args.account: raise ValueError('Choose --account or --new-account.')
                result = auth.login(no_browser=args.no_browser, port=args.callback_port, account=args.account, new=args.new_account)
            elif args.auth_action in ('status', 'accounts'): result = auth.status()
            elif args.auth_action == 'use': result = auth.use(args.account)
            else: result = auth.logout(args.account)
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        except KeyboardInterrupt: print('\nSign-in cancelled.'); return 130
        except Exception as exc: print(auth.clean_error(exc), file=sys.stderr); return 1
        finally: auth.close()
    if args.command == 'models':
        # Discovery has no gameplay effects and never needs a game installation.
        journal = Journal(Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'astrabridge-runner/discovery')
        api = None
        try:
            api = provider(args.provider, journal, args, '', '', args.account)
            models = api.models()
            if args.json: print(json.dumps(models, ensure_ascii=False, indent=2))
            else:
                for model in models: print(model['id'], '|', model['name'], '| context:', model['context_window'], '| reasoning:', model['reasoning_efforts'])
            return 0
        except Exception as exc: print(journal.clean(str(exc)), file=sys.stderr); return 1
        finally:
            if api: api.close()
            journal.close()
    resume = args.command == 'resume'
    if resume:
        try:
            saved = json.loads((args.session / 'manifest.json').read_text(encoding='utf-8'))
            if saved.get('schema') != 1: raise ValueError('Unsupported runner session format.')
        except Exception as exc: print(str(exc), file=sys.stderr); return 1
        parent = args.session.parent
    else:
        if not .01 <= args.compact_at <= .95: arguments.error('--compact-at must be between .01 and .95')
        if args.context_window is not None and args.context_window <= 1024: arguments.error('--context-window must exceed 1024 tokens')
        if args.base_url and args.provider != 'deepseek': arguments.error('--base-url is only available for DeepSeek')
        parent = args.log_dir
    # Acquire before opening/repairing an existing journal.
    lock = FileLock((args.session if resume else parent) / ('.session.lock' if resume else '.create.lock'), blocking=False)
    journal = None; api = None; runner = None
    try:
        with lock:
            journal = Journal(parent, resume=args.session if resume else None)
            if not resume:
                # The creation lock need not serialize the full session with
                # other independent profiles; use its own lifetime lock below.
                lock.__exit__()
            session_lock = FileLock(journal.root / '.session.lock', blocking=False) if not resume else None
            if session_lock: session_lock.__enter__()
            try:
                if resume:
                    args.base_url = saved['base_url']
                    if args.auth_dir is None:args.auth_dir=saved.get('auth_directory')
                    api = provider(saved['provider'], journal, args, saved['model'], saved['reasoning'], saved['account'])
                    runner = Runner(saved['skill'], journal, api, saved['executable'],
                                    context_window=saved['context_window'], compaction=saved['compaction'],
                                    image_limit=saved['image_limit'], compact_at=saved['compact_at'],
                                    on_text=lambda text: print(text, end='', flush=True))
                else:
                    api = provider(args.provider, journal, args, args.model, args.reasoning, args.account)
                    runner = Runner(args.skill, journal, api, args.astra, context_window=args.context_window,
                                    compaction=args.compaction != 'off', image_limit=args.image_context, compact_at=args.compact_at,
                                    on_text=lambda text: print(text, end='', flush=True))
                def status(value):
                    usage=value['last_api_usage'];actual=usage.get('input_tokens',usage.get('prompt_tokens'))
                    print(f"Context: ~{value['estimated_tokens']:,}/{value['window']:,} tokens; last API input: {actual if actual is not None else 'unknown'}",file=sys.stderr)
                runner.on_status=status
                context = runner.prepare(resume=resume)
                print('Session:', journal.root); print('Connected profile:', context['profile']['name'])
                print('Provider:', api.name, '| model:', api.model, '| reasoning:', api.effort)
                print('Enter a goal. /quit, EOF or Ctrl+C releases control and leaves the game paused.')
                text = args.task
                if resume and text is None:
                    runner.continue_turn()
                while not runner.stopped:
                    if text is None: text = input('\nTask> ')
                    if text.strip() == '/quit': break
                    if text.strip(): runner.turn(text)
                    text = None
                return 0
            except BaseException as exc:
                journal.event('runner_error',error=str(exc),interrupted=isinstance(exc,KeyboardInterrupt))
                raise
            finally:
                if runner: runner.close()
                else:
                    if api: api.close()
                    if journal: journal.close()
                if session_lock: session_lock.__exit__()
    except (EOFError, KeyboardInterrupt): print('\nRunner stopped.'); return 0
    except Exception as exc:
        text = journal.clean(str(exc)) if journal else str(exc)
        print(text, file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
