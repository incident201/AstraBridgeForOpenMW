# AstraBridge Runner

`astrabridge-runner` is an optional host Python application for playing through
native AstraBridge tools. It supports OpenAI through **Sign in with ChatGPT**
and the Responses API, and DeepSeek through its API. It manages transport,
history, images, context and logs. The model makes every game decision.

## Install and prepare

Use Python 3.11+, AstraBridge 0.3.5+ and the normal container/GPU prerequisites.
Install the `astrabridge_runner-0.1.0-py3-none-any.whl` in a Python environment,
or install the source package:

```sh
python3 -m venv /path/to/runner-venv
/path/to/runner-venv/bin/python -m pip install ./agent-runner
. /path/to/runner-venv/bin/activate
astrabridge skill export /path/to/api-skill --interface tools
```

On Windows, use the environment's `Scripts/python.exe` and
`Scripts/astrabridge-runner.exe`. Installation also installs HTTP, JSON Schema
and JWT/cryptography dependencies. They do not become container dependencies.

The exported skill contains the host application's executable and configuration
in `installation.json`. These bindings are host data and are not given to the
model. Start the game in the intended profile and release manual/agent control
before connecting. Each session stays associated with one installation and
game profile; another profile cannot resume its conversation.

## Sign in with ChatGPT

```sh
astrabridge-runner auth login
astrabridge-runner auth status
astrabridge-runner auth accounts
astrabridge-runner auth use ACCOUNT_ID
astrabridge-runner auth logout
```

Normal login opens the system browser. Add `--new-account` to register another
account/workspace, or `--account ACCOUNT_ID` to reauthorize a saved registration.
Multiple registrations may have the same email; their IDs and credentials stay
separate. A running session pins its selected registration.

For a headless host:

```sh
astrabridge-runner auth login --no-browser --callback-port 1455
```

Open the printed URL on the browser computer. If its final loopback page cannot
connect, copy that page's full address from the browser address bar and paste it
into the runner terminal. Input is hidden; the callback URL is not logged.
PKCE, state and ID-token validation still apply.

Alternatively, use `ssh -L 1455:127.0.0.1:1455 USER@HOST` to deliver the callback
automatically. The listener binds to `127.0.0.1`, with fixed path
`/auth/callback`; choose another port if needed. A declined or expired attempt
does not replace a previously signed-in account.

The client uses Authorization Code with PKCE and dynamic OSS registration.
ID-token signature, issuer, audience, expiry and nonce are verified. The issued
client ID and stable host ID are reused on later sign-ins. Credentials refresh
automatically, with refresh rotation serialized across processes.

Credentials default to `$XDG_CONFIG_HOME/astrabridge-runner`, or
`~/.config/astrabridge-runner` when unset. Windows uses
`%LOCALAPPDATA%/AstraBridgeRunner` and DPAPI credential protection. Unix files
are owner-only. Global `--auth-dir DIRECTORY` selects another protected store.
OAuth tokens are excluded from gameplay prompts, CLI children and session logs.

Sign-in and permission to use a plan are distinct. Inference requires the
granted `chatgpt.tokens.use.direct` scope and availability under the selected
account/workspace policy. Usage may be subject to app and plan limits. A denied
grant, exhausted limit or unavailable model stops inference; there is no API-key
billing fallback. Review app usage in ChatGPT Settings. Logout clears tokens
and attempts remote revocation while retaining the registration and host ID.

See the official [OSS sign-in guide](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
and [Responses route restrictions](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

## Choose a model and run

```sh
astrabridge-runner models --provider openai
astrabridge-runner run --provider openai --model MODEL --reasoning EFFORT \
  --skill /path/to/api-skill --log-dir /path/to/private-sessions \
  --task "Start a new game, complete the tutorial and save."
```

Choose a model advertised to your account. Reasoning effort uses the provider's
vocabulary; it is not silently translated or replaced. If the catalog does not
advertise a context window, supply `--context-window TOKENS` from the model's
documented limits. The selected settings and catalog snapshot are recorded.
`models --json` returns the catalog as JSON.

For DeepSeek, provide `DEEPSEEK_API_KEY` in the environment, then use:

```sh
astrabridge-runner models --provider deepseek
astrabridge-runner run --provider deepseek --model deepseek-flash --reasoning max \
  --skill /path/to/api-skill --log-dir /path/to/private-sessions
```

Do not put keys in arguments, source files or gameplay prompts. DeepSeek uses
its Chat Completions transport; OpenAI uses the public Responses endpoint with
OAuth, `store:false` and `stream:true`, not Codex or ChatGPT backend endpoints.

Enter goals at `Task>`. A text response without tools ends a turn; another goal
continues the same session. One tool call per model response is allowed. Batches
perform no game actions. Arguments use the exported schemas and fixed argv
bindings; models have no shell or Python scripting tools. Full returned JSON,
including movement diagnostics and errors, is retained.

OpenAI tools run only after `response.completed`. Incomplete/failed/interrupted
streams cannot execute partial calls. OpenAI output items, assistant phases and
encrypted reasoning are retained from completed stream items, including when
the terminal event has an empty output array. DeepSeek retains its reasoning
content.

## Images and context

The default active image window contains two recent selected frames;
`--image-context 1` selects one. New game screenshots/maps are archived before
the game's rolling cache can remove them. `view_saved_image` selects an older
registered frame and marks it historical. `read_skill_reference` reads a full
reference from the exported package. Neither tool accepts arbitrary files.

Checkpoint compaction is enabled for both providers. It triggers around 75% of
the configured context window, between completed tool cycles. The budget uses
actual API usage plus estimates for new items; estimates are not exact billing
counts. Ciphertext is not treated as plain reasoning text.

A separate request to the same model, without tools, creates a compact JSON
checkpoint: goal, existing plan, verified facts, uncertainty, failed attempts,
pending actions and references. It must not invent a new plan or copy inventory,
journal or stats that can be queried again. After validation, active context
keeps the rules, verbatim current request, checkpoint and eight complete recent
model cycles. The full journal remains intact. A failed checkpoint is retried
once; a failed or insufficient reduction stops the runner without discarding
the previous context. The checkpoint is runner memory, not an automatic write
to AstraBridge's knowledge database.

Use `--compaction off` for experiments with full active text history.
`--compact-at FRACTION` changes the trigger for testing or tuning.

## Stop and resume

`/quit`, EOF or Ctrl+C releases this runner's connection and leaves the game
paused. It does not automatically save the game, finalize recording, or remove
the container. Explicit game saving remains a model/player operation.

```sh
astrabridge-runner resume /path/to/private-sessions/SESSION
astrabridge-runner resume /path/to/private-sessions/SESSION --task "Reach the next town."
```

Resume restores native active context, settings, checkpoint and image archive.
It checks the installation, game profile, provider and ChatGPT registration;
it does not load a save or take over another controller. Older observations
and interaction handles become historical. Unfinished tool calls recover a
recorded result or an explicit unknown/not-executed result, including a receipt
request ID when available. They are not automatically executed again.

## Private session files

- `manifest.json`: provider/model/configuration, registration ID, installation,
  game profile, skill hash and model catalog.
- `active-state.json`: the current provider-native context and budget state.
- `events.jsonl`: complete model items, tool results, CLI output, lifecycle and errors.
- `api/*.json.gz`: full requests/responses, stream events, usage and diagnostics.
- `images.json` and `images/`: registered frames, original paths, hashes and image bytes.
- `checkpoint-*.json`: validated historical checkpoints.

Logs contain private playthrough data; they are for the host operator and are
not general model-readable files. OAuth/API credentials are not log data.
This package replaces the experimental DeepSeek-only runner and uses its own
session format.
