from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from .protocol import BridgeError, action_timeout, AIR_DIRECTIONS
from .session import Session
from .environment import identity
from .information import SECTIONS

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
SOCKET = RUNTIME / "bridge.sock"
PRETTY = False


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse otherwise repeats every top-level command in both usage
        # and its error, burying the one useful diagnostic.
        if 'invalid choice:' in message:
            message=message.split(' (choose from',1)[0]
        self.exit(2, f'{self.prog}: {message}. Use {self.prog} --help.\n')


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2 if PRETTY else None))


def request(op, args=None, timeout=130):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(action_timeout(op, args or {}, timeout))
        try:
            connection.connect(str(SOCKET))
        except OSError as exc:
            raise BridgeError("controller_not_running") from exc
        connection.sendall(json.dumps({"op": op, "args": args or {}}, ensure_ascii=False).encode() + b"\n")
        reader = connection.makefile("rb")
        data = reader.readline(4_000_001)
        if not data or len(data) > 4_000_000:
            raise BridgeError("controller_disconnected")
        return json.loads(data)


def serve(options):
    import fcntl
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    lock = open(RUNTIME / "controller.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise BridgeError("controller_already_running")
    os.umask(0o077)
    SOCKET.unlink(missing_ok=True)
    session = Session(ROOT, Path(options.installation), headless=options.headless,
                      display=options.display, sound=not options.no_sound, recordings_dir=options.recordings_dir)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(SOCKET))
    server.listen(4)
    def shutdown_signal(*_):
        session.control.interrupt()
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, shutdown_signal)
    signal.signal(signal.SIGINT, shutdown_signal)
    stopping = threading.Event()
    def handle(connection):
        with connection:
            connection.settimeout(5)
            try:
                raw = connection.makefile("rb").readline(32769)
                if len(raw) > 32768:
                    raise BridgeError("command_too_large")
                message = json.loads(raw)
                if type(message) is not dict or message.keys() - {"op", "args"}:
                    raise BridgeError("invalid_arguments")
                if message.get("op") == "shutdown":
                    result = session.control.execute('shutdown', message.get('args', {}))
                    stopping.set()
                else:
                    result = session.control.execute(message.get("op"), message.get("args", {}))
                    if message.get('op')=='finish_session' and result.get('closed'):stopping.set()
                response = {"ok": True, "result": result}
            except BridgeError as exc:
                response = {"ok": False, **exc.response()}
            except Exception:
                import traceback
                traceback.print_exc()  # private controller log, never the gameplay response
                response = {"ok": False, "error": "controller_operation_failed"}
            try:
                connection.sendall(json.dumps(response, ensure_ascii=False).encode() + b"\n")
            except OSError:
                pass  # disconnect does not replay or abandon an already bounded action
    try:
        session.start()
        server.settimeout(.2)
        with ThreadPoolExecutor(max_workers=4) as pool:
            while not stopping.is_set():
                try: connection, _ = server.accept()
                except socket.timeout: continue
                pool.submit(handle, connection)
    finally:
        session.control.interrupt()
        session.close()
        server.close()
        SOCKET.unlink(missing_ok=True)


def build_parser():
    parser = Parser(description="OpenMW player-visible harness")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version", help="Print frozen environment identity for benchmarks")
    for name in ("start", "serve"):
        p = commands.add_parser(name)
        p.add_argument("--installation", default=str(ROOT.parent))
        p.add_argument("--headless", action="store_true")
        p.add_argument("--display")
        p.add_argument("--no-sound", action="store_true")
        p.add_argument("--recordings-dir")
    for name in ("status", "observe", "stop", "saves", "new-game", "shutdown", "record-start", "record-stop", "record-status","scan","ui","route","map","unlock","survey","ground"):
        p=commands.add_parser(name)
        if name=='scan':p.add_argument('--pitch',dest='pitch_deg',type=float,default=0)
        if name=='status':p.add_argument('--player',action='store_true')
        if name=='observe':
            p.add_argument('--no-screenshot',action='store_true');p.add_argument('--map',action='store_true')
        if name=='ui':
            p.add_argument('--query');p.add_argument('--page',type=int,default=0);p.add_argument('--limit',type=int,default=20)
            p.add_argument('--panel');p.add_argument('--role');p.add_argument('--control')
    p=commands.add_parser('details',description='Page the latest public observation. For inventory, journal or spells use inspect.');p.add_argument('section',help='One of: '+', '.join(SECTIONS));p.add_argument('--observation',type=int)
    p.add_argument('--query');p.add_argument('--page',type=int,default=0);p.add_argument('--limit',type=int,default=20)
    p=commands.add_parser('action-result');p.add_argument('ref',nargs='?')
    p.add_argument('--view',type=int,help='Zero-based scan view; does not move the camera')
    p.add_argument('--section',choices=[*SECTIONS,'action','feedback','summary'])
    p.add_argument('--query');p.add_argument('--page',type=int);p.add_argument('--limit',type=int)
    p=commands.add_parser('autosave');p.add_argument('--enabled',action=argparse.BooleanOptionalAction,default=None)
    p.add_argument('--interval',type=float);p.add_argument('--slots',type=int)
    p=commands.add_parser('finish-session');p.add_argument('--description',default='Astra session end')
    p=commands.add_parser('comment',description='Publish a brief spectator comment without pausing gameplay.');p.add_argument('text')
    p=commands.add_parser('knowledge');p.add_argument('action',choices=['list','add','update','evidence','events','objects','checkpoint','brief'])
    p.add_argument('checkpoint',nargs='?',type=json.loads,help='JSON working state, only with knowledge checkpoint')
    p.add_argument('--object-ref',help='Persistent memory_ref from an observed object or knowledge objects')
    for field in ('kind','text','ref','status','evidence','quote','query'):p.add_argument('--'+field)
    for field in ('page','limit','offset'):p.add_argument('--'+field,type=int)
    p = commands.add_parser('read', help='Read the currently open book or scroll in bounded text chunks')
    p.add_argument('--ref'); p.add_argument('--offset', type=int, default=0); p.add_argument('--limit', type=int, default=4000)
    reading=p.add_mutually_exclusive_group();reading.add_argument('--all',action='store_true');reading.add_argument('--search')
    p=commands.add_parser('repair',help='Repeat normal hammer repair in the currently open repair menu')
    p.add_argument('name');p.add_argument('--attempts',type=int,default=1);p.add_argument('--condition-pct',type=float,default=100)
    p.add_argument('--instance')
    p = commands.add_parser('resetNPC', help='Emergency RA/ResetActors recovery of displaced actors in active cells')
    p.add_argument('--reason', required=True, help='Observed malfunction requiring this last-resort recovery')
    p = commands.add_parser("act"); p.add_argument("json", help='e.g. {"move":1,"seconds":0.4}')
    for name in ('jump','air-move'):
        p=commands.add_parser(name,description='One normal jump, or steering during a jump/fall. Stops on landing.')
        if name=='jump':p.add_argument('direction',choices=AIR_DIRECTIONS,nargs='?',default='none')
        else:p.add_argument('direction',choices=AIR_DIRECTIONS)
        p.add_argument('--run',action='store_true')
        p.add_argument('--seconds',type=float,default=8 if name=='jump' else .5,
                       help='Maximum simulation time; a short budget can leave the player airborne')
    p = commands.add_parser('look');p.add_argument('--heading',dest='heading_deg',type=float);p.add_argument('--pitch',dest='pitch_deg',type=float)
    p = commands.add_parser("chain"); p.add_argument("json", help='{"actions":[{"op":"strike"},{"op":"strike"}],"max_seconds":12}')
    p=commands.add_parser('sequence');p.add_argument('json')
    p=commands.add_parser('rest');p.add_argument('hours',type=int);p.add_argument('--seconds',type=float,default=30)
    p=commands.add_parser('buy');p.add_argument('name');p.add_argument('--quantity',type=int,default=1)
    p.add_argument('--max-total',type=int,required=True);p.add_argument('--instance');p.add_argument('--seconds',type=float,default=30)
    p=commands.add_parser('travel');p.add_argument('destination');p.add_argument('--max-cost',type=int);p.add_argument('--seconds',type=float,default=30)
    p=commands.add_parser('wait-until');p.add_argument('condition',choices=['fatigue','animation','passage','ui','controls','landed'])
    p.add_argument('--control',choices=['controls','looking','jumping'],help='For condition controls (default: controls)')
    p.add_argument('--percent',type=float,default=100);p.add_argument('--ui-mode');p.add_argument('--seconds',type=float,default=30)
    p.add_argument('--bearing-deg',type=float,default=0);p.add_argument('--meters',type=float,default=1)
    p = commands.add_parser('atlas'); p.add_argument('--radius-m',type=float,default=35)
    p.add_argument('--list', action='store_true'); p.add_argument('--space')
    p.add_argument('--history',action='store_true')
    p.add_argument('--query');p.add_argument('--page',type=int,default=0);p.add_argument('--limit',type=int,default=20)
    p.add_argument('--level');p.add_argument('--map',action='store_true');p.add_argument('--route')
    p = commands.add_parser('revisit'); p.add_argument('ref'); p.add_argument('--run',action='store_true')
    p.add_argument('--seconds',type=float,default=60); p.add_argument('--under-fire',action='store_true')
    p = commands.add_parser("inspect"); p.add_argument("view", choices=["stats", "inventory", "spells", "journal","conversations","combat","effects","character"]); p.add_argument("--page", type=int, default=0);p.add_argument('--topic')
    p.add_argument('--query');p.add_argument('--limit',type=int)
    for name in ('strike','cast'):
        p=commands.add_parser(name);p.add_argument('ref',nargs='?');p.add_argument('--air',action='store_true')
        if name=='strike':p.add_argument('--charge',type=float,default=.8)
    for name in ("use-item", "select-spell", "select-enchanted", "load","focus","approach","choose","lock","hover","target-info"):
        p = commands.add_parser(name); p.add_argument("ref")
        if name=='approach':p.add_argument('--reach',choices=['activate','melee','touch'],default='activate')
        if name=='approach':p.add_argument('--run',action='store_true')
        if name=='approach':p.add_argument('--under-fire',action='store_true')
        if name=='approach':p.add_argument('--seconds',type=float,default=30)
        if name=='focus':p.add_argument('--wait-ready',action='store_true')
    p=commands.add_parser('walk');p.add_argument('x',nargs='?',type=int);p.add_argument('y',nargs='?',type=int)
    p.add_argument('--observation',type=int);p.add_argument('--ref');p.add_argument('--run',action='store_true')
    p.add_argument('--under-fire',action='store_true')
    p.add_argument('--seconds',type=float,default=8)
    p=commands.add_parser('pick');p.add_argument('x',type=int);p.add_argument('y',type=int)
    p.add_argument('--radius',type=float,default=0);p.add_argument('--observation',type=int,required=True)
    p=commands.add_parser('go');p.add_argument('ref');p.add_argument('--run',action='store_true');p.add_argument('--seconds',type=float,default=12)
    p.add_argument('--under-fire',action='store_true')
    p=commands.add_parser('return-to');p.add_argument('ref');p.add_argument('--run',action='store_true');p.add_argument('--seconds',type=float,default=60)
    p.add_argument('--under-fire',action='store_true')
    for name in ('evade','retreat'):
        p=commands.add_parser(name)
        if name=='evade':p.add_argument('direction',choices=['left','right','back'])
        p.add_argument('ref',nargs='?');p.add_argument('--meters',type=float,default=2);p.add_argument('--seconds',type=float,default=4);p.add_argument('--run',action='store_true')
        p.add_argument('--actions',type=json.loads)
    p = commands.add_parser("save"); p.add_argument("description")
    p = commands.add_parser("edit"); p.add_argument("ref"); p.add_argument("text")
    p = commands.add_parser("adjust"); p.add_argument("ref"); p.add_argument("position",type=int)
    p = commands.add_parser("trigger"); p.add_argument("name")
    p = commands.add_parser("restart"); p.add_argument("--load-latest", action="store_true")
    p=commands.add_parser('interact');p.add_argument('ref');p.add_argument('--approach',action='store_true')
    p.add_argument('--adjust-viewpoint',action=argparse.BooleanOptionalAction,default=True)
    p.add_argument('--run',action='store_true');p.add_argument('--seconds',type=float,default=30);p.add_argument('--under-fire',action='store_true')
    p=commands.add_parser('move-local');p.add_argument('forward_m',type=float);p.add_argument('--sideways-m',type=float,default=0)
    p.add_argument('--under-fire',action='store_true')
    p.add_argument('--run',action='store_true');p.add_argument('--seconds',type=float,default=30)
    for mode in ('fly','swim'):
        p=commands.add_parser(mode);p.add_argument('--ref');p.add_argument('--forward-m',type=float,default=0);p.add_argument('--sideways-m',type=float,default=0)
        p.add_argument('--vertical-m',type=float,default=0);p.add_argument('--seconds',type=float,default=30 if mode=='swim' else 10);p.add_argument('--under-fire',action='store_true')
    p=commands.add_parser('fov');p.add_argument('degrees',type=float)
    p=commands.add_parser('track');p.add_argument('ref');p.add_argument('--seconds',type=float,default=1);p.add_argument('--attack',action='store_true')
    p=commands.add_parser('remember');p.add_argument('label');p.add_argument('--note',default='');p.add_argument('--exits',action='append',default=[]);p.add_argument('--confidence',choices=['observed','inferred'],default='observed')
    p=commands.add_parser('recall');p.add_argument('query',nargs='?',default='');p.add_argument('--archived',action='store_true')
    p=commands.add_parser('connect');p.add_argument('from');p.add_argument('to');p.add_argument('--via',required=True)
    p = commands.add_parser("click"); p.add_argument("x", type=int); p.add_argument("y", type=int); p.add_argument("--button", type=int, default=1); p.add_argument("--observation", type=int, required=True)
    for name, field in (("key", "key"), ("text", "text"), ("scroll", "steps")):
        p = commands.add_parser(name); p.add_argument(field, type=int if name == "scroll" else str); p.add_argument("--observation", type=int, required=True)
    for name,command_parser in commands.choices.items():
        if name not in {'start','serve','comment'}:
            command_parser.add_argument('--full',action='store_true',default=argparse.SUPPRESS)
            command_parser.add_argument('--request-id',default=argparse.SUPPRESS)
            command_parser.add_argument('--pretty',action='store_true',default=argparse.SUPPRESS)
    commands.choices['comment'].add_argument('--pretty',action='store_true',default=argparse.SUPPRESS)
    return parser


def main():
    global PRETTY
    options = build_parser().parse_args()
    PRETTY=vars(options).pop('pretty',False)
    try:
        if options.command == "version":
            emit(identity(ROOT))
            return
        if options.command == "serve":
            serve(options)
            return
        if options.command == "start":
            # shutdown closes the game before the server socket disappears.
            # Do not report that dying controller as a successful new start.
            deadline = time.monotonic()+5
            while True:
                try:
                    existing = request("status", timeout=2)
                except (BridgeError, OSError):
                    break
                if existing.get("ok") and existing.get("result",{}).get("running"):
                    emit(existing); return
                if time.monotonic()>=deadline:
                    raise BridgeError("controller_without_game_use_restart")
                time.sleep(.1)
            RUNTIME.mkdir(mode=0o700, exist_ok=True)
            cmd = [sys.executable, "-m", "astra_bridge.cli", "serve", "--installation", options.installation]
            if options.headless: cmd.append("--headless")
            if options.display: cmd += ["--display", options.display]
            if options.no_sound: cmd.append("--no-sound")
            if options.recordings_dir: cmd += ['--recordings-dir',options.recordings_dir]
            with open(RUNTIME / "controller-private.log", "ab") as log:
                process = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            deadline = time.monotonic()+75
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise BridgeError("startup_failed_see_private_controller_log")
                if SOCKET.exists():
                    try:
                        emit(request("status", timeout=70)); return
                    except (BridgeError, OSError):
                        pass
                time.sleep(.1)
            raise BridgeError("startup_timeout")
        op = options.command.replace("-", "_")
        args = vars(options).copy(); args.pop("command")
        args={k:v for k,v in args.items() if v is not None}
        if op in {"act","chain","sequence"}:
            full=args.get('full',False)
            request_id=args.get('request_id')
            args = json.loads(args["json"])
            if full:args['full']=True
            if request_id:args['request_id']=request_id
        if op=='read' and not args.get('all'):args.pop('all',None)
        response = request(op, args)
        emit(response)
        if not response["ok"]:
            sys.exit(1)
    except (BridgeError, OSError, ValueError) as exc:
        emit({"ok": False, **(exc.response() if isinstance(exc,BridgeError) else {'error':'invalid_request_or_connection'})})
        sys.exit(1)


if __name__ == "__main__":
    main()
