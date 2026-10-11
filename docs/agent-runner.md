# AstraBridge Runner

`astrabridge-runner` is an optional host Python application for playing through
native AstraBridge tools. It supports OpenAI through **Sign in with ChatGPT**
and the Responses API, DeepSeek through its API, and Grok through the xAI
Responses API with an API key. It manages transport,
history, images, context and logs. The model makes every game decision.

## Install and prepare

Use Python 3.11+, AstraBridge 0.3.5+ and the normal container/GPU prerequisites.
Install the `astrabridge_runner-0.1.2-py3-none-any.whl` in a Python environment,
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

For Grok, provide `XAI_API_KEY` in the environment, then use:

```sh
astrabridge-runner models --provider grok --json
astrabridge-runner run --provider grok --model grok-4.7 --reasoning xhigh \
  --skill /path/to/api-skill --log-dir /path/to/private-sessions \
  --task "Start a new game, complete the tutorial and save."
```

Grok uses `https://api.x.ai/v1/responses` with Bearer API-key authorization.
Grok 4.7 supports `low`, `medium`, `high` and `xhigh`; the runner requires an
explicit choice. `--base-url` remains a DeepSeek option. Grok model discovery
uses the account's `/language-models` catalog and accepts aliases advertised
there. When that catalog omits context or effort metadata for an available
Grok 4.7, the runner uses its documented 500,000-token context and effort
levels. Explicit API metadata takes precedence. See the official
[Grok 4.7 guide](https://docs.x.ai/developers/grok-4-7) and
[model discovery reference](https://docs.x.ai/developers/rest-api-reference/inference/models).

Grok requests use `store:false`, flat function tools and
`parallel_tool_calls:false`. Its encrypted reasoning items are retained and
passed back unchanged. A stable prompt cache key belongs to the session and
survives resume. The HTTP read timeout is one hour for Grok reasoning; connection
and request-write timeouts remain bounded separately. See
[xAI reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning).

The Grok adapter expresses argument alternatives below an object schema root,
because xAI rejects tool schemas with root `anyOf`/`oneOf` alternatives. This is
an equivalent transformation of the exported schemas; the runner still validates
arguments against the original AstraBridge definitions before executing a tool.

Do not put keys in arguments, source files or gameplay prompts. DeepSeek uses
its Chat Completions transport; OpenAI uses the public Responses endpoint with
OAuth, `store:false` and `stream:true`, not Codex or ChatGPT backend endpoints.
API keys are redacted from logs and removed from the environment passed to
AstraBridge CLI processes. Grok uses only the exported game and runner resource
tools; xAI search and code-execution tools are not enabled.

Enter goals at `Task>`. A text response without tools ends a turn; another goal
continues the same session. One tool call per model response is allowed. Batches
perform no game actions. Arguments use the exported schemas and fixed argv
bindings; models have no shell or Python scripting tools. Full returned JSON,
including movement diagnostics and errors, is retained.

OpenAI and Grok tools run only after `response.completed`. Incomplete/failed/interrupted
streams cannot execute partial calls. Responses output items, assistant phases and
encrypted reasoning are retained from completed stream items, including when
the terminal event has an empty output array. DeepSeek retains its reasoning
content.

## Images and context

The default active image window contains two recent selected frames;
`--image-context 1` selects one. New game screenshots/maps are archived before
the game's rolling cache can remove them. `view_saved_image` selects an older
registered frame and marks it historical. `read_skill_reference` reads a full
reference from the exported package. Neither tool accepts arbitrary files.

Checkpoint compaction is enabled for all providers. It triggers around 75% of
the configured context window, between completed tool cycles. The budget uses
actual API usage plus estimates for new items; estimates are not exact billing
counts. Ciphertext is not treated as plain reasoning text.
The budget includes reasoning tokens when xAI reports them separately from
visible completion tokens; the original API usage remains in the logs.

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
Resuming a Grok session requires `XAI_API_KEY` in the environment again. Keys
are not saved in the session archive.

## Private session files

- `manifest.json`: provider/model/configuration, registration ID, installation,
  game profile, skill hash and model catalog.
- `active-state.json`: the current provider-native context and budget state.
- `events.jsonl`: complete model items, tool results, CLI output, lifecycle and errors.
- `api/*.json.gz`: reconstructable full requests/responses, stream events, usage
  and diagnostics. Requests reference archived image bytes instead of storing
  repeated base64 copies of the same screenshot. The `image_archive` field maps
  each reference to its image file, SHA256 and exact positions in the request.
- `images.json` and `images/`: registered frames, original paths, hashes and image bytes.
- `checkpoint-*.json`: validated historical checkpoints.

Logs contain private playthrough data; they are for the host operator and are
not general model-readable files. OAuth/API credentials are not log data.
This package replaces the experimental DeepSeek-only runner and uses its own
session format.

### Storage and archive cleanup

The active session's complete text history and image archive are retained;
compaction only changes model context. Logs therefore still grow during a long
session. Repeated API screenshots share the files in `images/`.
`astrabridge_runner.journal.read_api_record(session_directory, relative_path)`
restores the original JSON request, including image data URLs, and verifies image
hashes. It also reads older records with inline images without modifying them.

Preview cleanup of old inactive sessions:

```sh
astrabridge-runner logs prune --log-dir /path/to/private-sessions
```

This keeps the five most recent sessions and selects older sessions only after
30 days without activity. `--older-than-days DAYS` and `--keep-last COUNT`
change those limits. Add `--delete` to remove the selected archives:

```sh
astrabridge-runner logs prune --log-dir /path/to/private-sessions \
  --older-than-days 30 --keep-last 5 --delete
```

Cleanup removes entire selected session directories, including their API logs,
screenshots and resume state. Active sessions, unrelated directories and
symlinked session directories are skipped. There is no automatic removal of
playthrough history; archive anything you want to keep before deletion.
Model discovery uses separate archives under
`$XDG_STATE_HOME/astrabridge-runner/discovery` (or
`~/.local/state/astrabridge-runner/discovery` when unset). Pass that directory as
`--log-dir` to apply the same cleanup policy to discovery logs.

### API retries

Transient HTTP errors (429, 500, 502, 503 and 504) and network failures get at
most three attempts. Exponential backoff respects `Retry-After` seconds or an
HTTP date in both providers. If the server requests a wait longer than 60
seconds, the runner stops retrying and retains the session for later resume.
Permanent errors and ChatGPT subscription usage limits are not retried.
