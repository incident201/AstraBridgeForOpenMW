# In-game maps

All commands below follow `astrabridge game`. These show the game's own Map
window, including its fog of exploration, player arrow and ordinary markers.
`atlas` is separate: it remembers your travelled routes and notes. A map label
does not provide a movement target or prove a walkable route.

| Command | Behavior |
|---|---|
| `map` | Open the regular, smaller game window alongside the scene. |
| `map local` | Open the large local map, centered on the player at normal zoom or the minimum needed to fill the view. |
| `map world` | Open the large world map at its widest zoom. |
| `map view` | Get the current map image without resetting its view. |
| `map pan --dx X --dy Y` | Move the viewing area by fractions of its width/height. Positive X is right, positive Y is down. Omit either axis for zero; each must be within −10…10. |
| `map zoom --factor F` | Multiply zoom about the viewport center: 2 zooms in, 0.5 zooms out. F is 0.25…4 per call. |
| `map zoom --fit` | Widest allowed zoom for the selected map. Does not change local/world mode. |
| `map center` | Center on the player arrow without changing zoom. Indoors, the world map uses the game's last exterior position. |
| `map markers [--query TEXT] [--page N] [--limit N]` | Read visible labels and normal tooltip notes without another image. Default page 0, limit 20; maximum limit 1000. |
| `map close` | Close the map and restore its ordinary window size. The game stays paused until the next gameplay action. |

For large views, open **`result.map.image`** with your image-viewing tool. This is
a fresh completed game frame at native resolution, normally 1920×1080; the same
view appears in Desktop and recordings. These calls omit a duplicate ordinary
screenshot. `map markers` returns text only.

`map` data report `view_mode`, `fullscreen`, `zoom`, `min_zoom`, `max_zoom`,
`limit_reached` and `can_pan_left/right/up/down`. At a limit, choose another
direction or zoom instead of repeating the same request. Pan/zoom/view/center/
markers/close require an open map and return `map_not_open` otherwise.

The `markers` list contains only labels whose normal tooltips are available in
the current visible area. Each row has `text`, optional notes in `description`,
and `image_x`/`image_y` normalized to the entire image (0…1 from top-left).
`total`, `page`, `limit` and `has_more` describe the list; query `map markers` for
additional rows. Fog-hidden doors, offscreen labels and hidden members of grouped
markers are not disclosed. Known names on this map do not change the scene's
distance-based identification rules or add Atlas knowledge automatically.

Map image coordinates are **not** coordinates for `click`, `pick` or `walk`.
Use the semantic map commands. If a raw UI click is necessary, first obtain an
ordinary `observe` screenshot and use its 720p coordinates and observation ID.

Example:

```sh
astrabridge game map local
# Open result.map.image, then choose the next view from what it shows.
astrabridge game map pan --dx 0.5
astrabridge game map zoom --factor 2
astrabridge game map markers
astrabridge game map center
astrabridge game map close
```

Unavailable tutorial controls return `view_unavailable`. A blocking modal or
another menu returns `ui_open`; handle that UI through its normal controls first.
Do not dismiss it blindly. Viewing the map does not advance game simulation;
actual map interactions are retained in recording, with reasoning pauses omitted.
