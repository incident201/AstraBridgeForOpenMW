import argparse
import json
import os
import sys
from pathlib import Path

from .auth import AuthStore
from .journal import Journal
from .locking import FileLock
from .logs import prune_sessions
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
    logs = sub.add_parser('logs', help='Manage private runner session archives')
    log_actions = logs.add_subparsers(dest='logs_action', required=True)
    prune = log_actions.add_parser('prune', help='Preview deletion of old inactive sessions')
    prune.add_argument('--log-dir', type=Path, default=Path('astrabridge-sessions'))
    prune.add_argument('--older-than-days', type=float, default=30)
    prune.add_argument('--keep-last', type=int, default=5)
    prune.add_argument('--delete', action='store_true', help='Delete selected sessions; omitted means dry run')
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
    if args.command == 'logs':
        try:
            result = prune_sessions(
                args.log_dir, older_than_days=args.older_than_days,
                keep_last=args.keep_last, delete=args.delete,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result['errors'] else 0
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
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
        parent = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'astrabridge-runner/discovery'
        journal = None
        session_lock = None
        api = None
        try:
            with FileLock(parent / '.create.lock', blocking=False):
                journal = Journal(parent)
                session_lock = FileLock(journal.root / '.session.lock', blocking=False)
                session_lock.__enter__()
                journal.write('manifest.json', {'schema': 1, 'provider': args.provider, 'kind': 'discovery'})
            api = provider(args.provider, journal, args, '', '', args.account)
            models = api.models()
            if args.json: print(json.dumps(models, ensure_ascii=False, indent=2))
            else:
                for model in models: print(model['id'], '|', model['name'], '| context:', model['context_window'], '| reasoning:', model['reasoning_efforts'])
            return 0
        except Exception as exc:
            print(journal.clean(str(exc)) if journal else str(exc), file=sys.stderr)
            return 1
        finally:
            try:
                if api:
                    api.close()
            finally:
                try:
                    if journal:
                        journal.close()
                finally:
                    if session_lock:
                        session_lock.__exit__()
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
    # Coordinate creation/resume with archive cleanup before opening a journal.
    lock = FileLock(parent / '.create.lock', blocking=False)
    journal = None; api = None; runner = None
    session_lock = None
    try:
        with lock:
            try:
                if resume:
                    if not args.session.is_dir() or not (args.session / 'manifest.json').is_file():
                        raise ValueError('The runner session archive no longer exists.')
                    session_lock = FileLock(args.session / '.session.lock', blocking=False)
                    session_lock.__enter__()
                journal = Journal(parent, resume=args.session if resume else None)
                if not resume:
                    session_lock = FileLock(journal.root / '.session.lock', blocking=False)
                    session_lock.__enter__()
                # Independent profiles need not hold the parent lock for the
                # full run; the session's own lock protects its complete log.
                lock.__exit__()
            except BaseException:
                if session_lock:
                    session_lock.__exit__()
                if journal:
                    journal.close()
                raise
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
                try:
                    if runner:
                        runner.close()
                    else:
                        try:
                            if api:
                                api.close()
                        finally:
                            if journal:
                                journal.close()
                finally:
                    if session_lock:
                        session_lock.__exit__()
    except (EOFError, KeyboardInterrupt): print('\nRunner stopped.'); return 0
    except Exception as exc:
        text = journal.clean(str(exc)) if journal else str(exc)
        print(text, file=sys.stderr); return 1


if __name__ == '__main__': sys.exit(main())
