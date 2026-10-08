# Direct DeepSeek runner

`deepseek-runner` is a small host-side Python component for playing Morrowind
through AstraBridge native tools. It connects directly to the official DeepSeek
API and targets **DeepSeek-V4.1-Flash with max reasoning effort**. No Codex CLI
or model-controlled shell is involved.

## Requirements and setup

Use Python 3.11 or newer, AstraBridge 0.3.5 or newer, and a DeepSeek API key with
access to image input and max effort. The
existing AstraBridge container/GPU requirements still apply to running the game.
The runner's HTTP client and schema validator are installed on the host; they
are not added to the production OCI image.

Download the optional `astrabridge_deepseek_runner-0.1.0-py3-none-any.whl` from
the AstraBridge GitHub release. Install it into a host Python environment:

```sh
python3 -m venv /path/to/runner-venv
/path/to/runner-venv/bin/python -m pip install /path/to/astrabridge_deepseek_runner-0.1.0-py3-none-any.whl
astrabridge agent tools --json
astrabridge skill export /path/to/api-skill --interface tools
```

For development, install `./deepseek-runner` from a source checkout instead of
the wheel. On Windows, use the environment's `Scripts/python.exe` and
`Scripts/deepseek-runner.exe`; the wheel supports both host platforms.

Supply `DEEPSEEK_API_KEY` through the process environment or your secret manager.
Do not put it in command arguments, committed files or a gameplay prompt.

```sh
/path/to/runner-venv/bin/deepseek-runner \
  --skill /path/to/api-skill --log-dir /path/to/private-sessions
```

The exported `installation.json` tells the host runner which application and
configuration to use. It is not part of the model prompt. `--astra` is an
explicit host executable override. The selected Desktop profile is used, and a
running human or another agent must release control before connecting.

The default API endpoint is `https://api.deepseek.com`; model ID
`deepseek-flash` is checked against the API's advertised
`DeepSeek-V4.1-Flash` identity, image support and `max` effort. `--base-url` and
`--model` allow an explicit DeepSeek deployment override. There is no provider
abstraction or automatic fallback to another model.

## Interaction

Enter a goal at `Task>`. The model receives the native-tool skill and all
exported game-tool definitions. It decides which tools to call and receives
their actual structured results. A text answer without tool calls ends the
current turn; another user message continues the same full conversation.
`--task TEXT` supplies the initial goal before the interactive prompt.

Only one tool call is accepted per model response. A batch gets an error result
for every call and performs no game actions. Tool names and arguments are
validated against the exported schemas; execution uses fixed executable/argv
bindings with `shell=False`. The model cannot supply an executable, environment,
installation path or arbitrary script.

Results retain the normal AstraBridge format. The runner does not discard
feedback, summary, motion, observations or error diagnostics. AstraBridge's
usual compact view remains the default; models can request `full` or use
existing detail/query tools when more information is needed.

`read_skill_reference` reads a complete reference from the exported package by
ID. `view_saved_image` selects a previously returned image by `image_ref`.
Neither utility accepts arbitrary filesystem paths.

## Text and images

The entire text history, including assistant `reasoning_content`, is retained
and sent on subsequent requests. There is no history compaction, summarization
or text eviction. Context/body-limit errors stop the turn and retain the log.

New screenshots and large game-map images are copied into the session archive
before AstraBridge can clean its cache. Only the last selected image block is
sent to DeepSeek; older messages keep their text and diagnostics. Image captions
associate the frame with the corresponding tool call. A scan archives its views
and selects the final frame. Images quoted in remembered places are available
by reference and do not automatically replace the current view.

An explicitly selected older image is marked historical. It must not be used as
proof of the current state or with stale interaction handles. The next fresh
observation supplies a current image through the same transport.

## Lifecycle and logs

Every launch creates a new session; history restoration after restarting the
runner is not implemented. `/quit`, EOF or Ctrl+C release this runner's agent
connection. A running action is interrupted through the ordinary stop channel.
This leaves the game paused; it does not automatically save, finalize recording
or delete the container. The model may use the existing explicit finish-session
tool when the user requests it.

The connection uses a temporary private configuration so another client's
token cannot be picked up accidentally. Host stop or loss of ownership ends
runner activity without taking over or reconnecting. Uncertain action results
are not automatically repeated; the existing action receipt can be recovered
by its request ID.

Each private session directory contains:

- `events.jsonl`: model messages, tool calls/results, complete CLI stdout/stderr,
  exit codes, timing, image references and lifecycle events.
- `api/*.json.gz`: complete API request/response bodies, available usage and
  diagnostic metadata. Compression changes storage only, not model context.
- `history.json`: the full text conversation and registered image references.
- `images.json` and `images/`: original paths, copied image bytes, hashes and
  available dimensions.
- `tools.json`: the exact exported definitions and application identity.

API credentials are excluded from logs and child-process environments. Logs
may contain the full playthrough and are intended for the host operator, not as
a model-accessible resource.
