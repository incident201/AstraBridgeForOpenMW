# AstraBridge Runner: technical reference

For installation from a release wheel and a first game session, start with
[Using AstraBridge Runner](agent-runner.md). This page covers optional settings
and implementation details.

## Additional CLI options

| Option | Where | Purpose |
| --- | --- | --- |
| `--account ACCOUNT_ID` | `run`, `models` | Select a saved ChatGPT registration explicitly. |
| `--auth-dir DIRECTORY` | Before the subcommand | Select another protected ChatGPT credential store. |
| `--image-context 1` | `run` | Keep one recent selected screenshot in active context instead of two. |
| `--compaction off` | `run` | Retain active text history until the model context limit is reached. |
| `--compact-at FRACTION` | `run` | Change the checkpoint trigger; default `0.75`, accepted range `0.01`–`0.95`. |
| `--context-window TOKENS` | `run` | Supply the documented model context size when discovery does not report one. Values must exceed 1024. |
| `--astra EXECUTABLE` | `run` | Override the executable from the exported installation metadata. |
| `--base-url URL` | `run`, DeepSeek only | Use a compatible DeepSeek deployment. HTTPS is required except for loopback addresses. |
| `--json` | `models`, `logs stats` | Print machine-readable output. |

`resume` restores the saved model, effort, context settings, executable and
installation. It accepts a new `--task`, not a new provider or model.

For full syntax, run `astrabridge-runner --help` or add `--help` after a
subcommand. To develop the runner from source, see [development](development.md).

## ChatGPT accounts and credentials

```sh
astrabridge-runner auth accounts
astrabridge-runner auth login --new-account
astrabridge-runner auth login --account ACCOUNT_ID
astrabridge-runner auth use ACCOUNT_ID
astrabridge-runner auth logout --account ACCOUNT_ID
```

`--new-account` adds a registration; `--account` reauthorizes an existing one.
Registrations can share an email but retain distinct IDs and credentials.
`auth use` changes the default for new sessions; an existing session pins its
registration. Logout clears tokens and attempts remote revocation while
retaining the registration and host ID.

Credentials default to `$XDG_CONFIG_HOME/astrabridge-runner`, or
`~/.config/astrabridge-runner` when unset. Windows uses
`%LOCALAPPDATA%/AstraBridgeRunner` with DPAPI protection. Unix files are owner-only.
A separate store can be selected with:

```sh
astrabridge-runner --auth-dir /path/to/credentials auth status
```

Authorization uses PKCE, dynamic client registration and a stable host ID.
ID-token validation includes signature, issuer, audience, expiry and nonce;
refresh-token rotation is serialized across processes. API keys and OAuth tokens
are excluded from gameplay prompts, CLI child environments and session logs.

For headless sign-in, pasting the callback URL into the waiting terminal is
supported. An SSH tunnel is an alternative:

```sh
ssh -N -L 1455:127.0.0.1:1455 USER@RUNNER_HOST
```

Then, on the runner host:

```sh
astrabridge-runner auth login --no-browser --callback-port 1455
```

The callback listener binds to loopback. Keep the tunnel open while signing in
from the browser computer. Choose another port on both commands if needed.

Inference requires the `chatgpt.tokens.use.direct` grant and account/workspace
access. See the official [sign-in guide](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
and [route limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

## Provider transport and tools

| Provider | Endpoint | Conversation state |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1/responses` | Streamed Responses items, including assistant phases and opaque reasoning. |
| DeepSeek | `https://api.deepseek.com/responses` | Streamed Responses items, including native `reasoning_text`. |
| Grok | `https://api.x.ai/v1/responses` | Streamed Responses items, including encrypted reasoning. |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/interactions` | Complete native steps, including thought signatures. |
| MiMo | `https://api.xiaomimimo.com/v1/responses` | Streamed Responses items, including native reasoning text. Authenticated with `MIMO_API_KEY`. |

All adapters use client-owned history. All except MiMo send `store:false`;
MiMo omits the undocumented `store` parameter. Grok requests encrypted
reasoning and uses a session-specific prompt cache key that survives resume.
Gemini uses implicit caching and returns non-streamed responses. Connection and
write timeouts are separate from read timeouts; Gemini and Grok permit an hour
for a reasoning response.

Tool schemas and CLI invocation bindings come from `astrabridge agent tools
--json`. The runner does not maintain another set of gameplay definitions.
Arguments are checked against the original schemas before execution. Grok's
schema adapter moves root alternatives below an object conjunction; Gemini's
adapter declares properties inside required-only conditional branches. These
transformations preserve the original argument constraints.

Only AstraBridge tools and the runner's skill/image resource tools are exposed.
There are no shell, arbitrary-file, search or code-execution tools. One tool
call per response is allowed; batches receive errors without executing actions.
Responses tools run only after `response.completed`; Gemini tools require a
successful completed or requires-action response. Partial calls are not executed.

Model discovery uses the provider catalog. Grok accepts advertised aliases and
uses documented defaults for Grok 4.7 when its catalog omits context/effort
metadata. Gemini combines the catalog with its adapter's supported model/effort
list. Unknown capabilities fail rather than silently substituting a model.

MiMo checks the account's model catalog and supplies the documented 1M-token
context window and image support for V2.6 Pro, Flash and Pro Ultraspeed when
the catalog omits capabilities. `none` disables thinking; all other accepted
reasoning levels currently enable the same mode. Native reasoning text is
retained across tool turns. MiMo omits undocumented `parallel_tool_calls` and
image `detail` fields; the runner still enforces one tool call per response.

Provider references: [OpenAI Responses](https://developers.openai.com/api/reference/resources/responses/methods/create),
[DeepSeek Responses](https://api-docs.deepseek.com/api/create-response/),
[xAI reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning),
[Gemini Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview),
[MiMo Responses](https://mimo.mi.com/docs/en-US/api/chat/responses) and
[MiMo model capabilities](https://mimo.mi.com/docs/en-US/quick-start/summary/model).

## Context and checkpoints

The context budget combines reported API usage with estimates for newly added
items. Opaque signatures/ciphertext are not tokenized as ordinary text. A
checkpoint request goes to the same model without gameplay tools. Its shared
schema contains `goal`, `plan`, `facts`, `uncertainties`, `failed_attempts`,
`pending_actions` and `references`.

OpenAI, Grok and DeepSeek receive `text.format` with `json_schema`; OpenAI and
Grok also receive `strict:true`. Gemini receives a JSON `response_format` and
schema. Local validation additionally enforces field limits and a 12,000-byte
UTF-8 budget. OpenAI commentary stays in the log; its `final_answer`, when
present, supplies the checkpoint JSON.

MiMo uses `text.format: {"type":"json_object"}` rather than unsupported strict
JSON Schema output. The shared checkpoint instruction defines the fields and
the same local schema and size validation applies before replacing history.

A valid checkpoint replaces older active history, retaining the instructions,
verbatim current request and eight complete recent model cycles. A checkpoint
is model-written memory: it does not establish facts or write automatically to
AstraBridge's knowledge database. Invalid checkpoints are retried once. Failed
or insufficient compaction leaves the previous context intact and stops the
runner.

All providers receive a stable chronological text history followed by a transient
suffix containing the selected one or two screenshots. Source captions stay at
the original tool-result positions; attachments repeat their image reference,
call ID and historical label. Replacing a selected image therefore does not
rewrite earlier text messages. Native model outputs and reasoning signatures
retain their original order and contents. The suffix is rebuilt for each request
and is not added to saved conversation history.

This layout supports prefix caching without retaining every old image in the
active context. Provider cache hits are still not guaranteed. A changed task,
checkpoint compaction or provider cache expiry can reduce reuse. Existing runner
sessions keep their saved format and use the new layout when resumed.

Images are archived before AstraBridge's rolling screenshot cache removes them.
`view_saved_image` can select a previously registered frame and labels it as
historical. `read_skill_reference` reads full references from the exported skill.
Neither resource tool accepts arbitrary host files.

## Session archives and statistics

| File | Contents |
| --- | --- |
| `manifest.json` | Provider/model/configuration, installation/profile identity, skill hash and catalog snapshot. |
| `active-state.json` | Provider-native active history and context budget state. |
| `events.jsonl` | Model items, tool results, CLI output, lifecycle, errors and usage events. |
| `usage.json` | Last-request counters, totals and inference/checkpoint breakdowns. |
| `api/*.json.gz` | Reconstructable requests/responses, stream events and diagnostics. |
| `images.json`, `images/` | Registered screenshots and their metadata. |
| `checkpoint-*.json` | Validated conversation checkpoints. |

Repeated request images share archived bytes. The request's `image_archive`
metadata records hashes and positions needed for reconstruction.
`astrabridge_runner.journal.read_api_record(session_directory, relative_path)`
restores the original request and verifies image hashes. Older inline-image
archives are also readable.

Usage totals count API attempts separately, including checkpoint retries.
Reasoning is part of output and cached input is part of input. Missing counters
remain `null`; `reported_requests` records coverage for each total. Cache ratio
uses only requests reporting both input and cached input. Interrupted requests
may have no usage, so these totals are not a substitute for provider billing.
Older events without a purpose are classified as `unclassified`.

Resume rebuilds statistics from events and restores native context. It verifies
the installation, profile, skill and provider. Pending calls recover a recorded
result or an explicit unknown/not-executed result, including a receipt ID when
available; they are not automatically replayed.

To customize archive cleanup:

```sh
astrabridge-runner logs prune --log-dir /path/to/sessions --older-than-days 30 --keep-last 5
```

Add `--delete` to apply the preview. Active sessions, unrelated directories and
symlinked session directories are skipped. Discovery logs are separate, under
`$XDG_STATE_HOME/astrabridge-runner/discovery`, or
`~/.local/state/astrabridge-runner/discovery` when unset; that directory can also
be supplied to `--log-dir` for cleanup.

## Retries and interrupted requests

Transient HTTP errors (429, 500, 502, 503 and 504) have at most three attempts.
Backoff respects `Retry-After` seconds or an HTTP date. A requested wait over
60 seconds stops retries. Permanent errors and ChatGPT subscription-limit
errors are not retried.

Network failures before a streamed response starts can be retried. Interrupted
Responses streams are retained as errors and do not execute partial tools.
The runner preserves the session for later inspection or resume.
