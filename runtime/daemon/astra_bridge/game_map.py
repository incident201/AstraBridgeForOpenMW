"""Large screenshots of the game's MapWindow, never an independent world map."""
from .information import page_rows
from .observations import prune_screenshots
from .protocol import BridgeError, validate


def view_map(session, args):
    action = args.get('action')
    paging = {k:v for k,v in args.items() if k in {'query','page','limit'}}
    native = {k:v for k,v in args.items() if k not in paging}
    validate('map', native)
    if paging and action != 'markers':
        raise BridgeError('invalid_arguments')
    page_rows([], paging)  # Validate before opening/changing anything.
    with session.record_ui():
        submitted = session.command('map', native)
        if action == 'close':
            return {'action':submitted, 'observation':session.observe()}
        if action == 'markers':
            state = submitted['map']
            rows, metadata = page_rows(state.pop('markers', []), paging)
            return {'map':{**state, 'markers':rows, **metadata}}
        # Establish a normal paused observation without generating a duplicate
        # 720p image. Existing click/observe coordinates remain unchanged.
        observation = session.observe(capture=False)
        state = session.command('map', {'action':'view'})['map']
        path = session.runtime/'screenshots'/f'{session.session_id[:8]}-{observation["observation"]:06}-map.png'
        stream = session.display.frame_stream
        if not stream or not stream.supported:
            raise BridgeError('engine_frame_unavailable_rebuild_engine')
        size = stream.capture(path, native_size=True)
        rows, metadata = page_rows(state.pop('markers', []), {})
        state.update(markers=rows, **metadata, image=str(path), **size,
                     limit_reached=submitted['map'].get('limit_reached', False))
    prune_screenshots(session.runtime/'screenshots', session.memory, session.screenshot_keep)
    return {'map':state, 'observation':observation}
