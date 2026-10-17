# AstraBridge Runner: user guide

The runner lets an AI model play your game through AstraBridge. You choose a
model, type a goal, and watch it play in AstraBridge Desktop.

It runs in a terminal on your computer, outside the game container. You need
AstraBridge installed and configured, plus **Python 3.11 or newer**. You do not
need Codex CLI or another agent application.

- [Install](#1-install)
- [Update or uninstall](#2-update-or-uninstall)
- [Prepare AstraBridge](#3-prepare-astrabridge)
- [Sign in or enter an API key](#4-sign-in-or-enter-an-api-key)
- [Choose a model and start](#5-choose-a-model-and-start)
- [Give the model a task](#6-give-the-model-a-task)
- [Stop and resume](#7-stop-and-resume)
- [Logs, usage and common problems](#8-logs-usage-and-common-problems)

## 1. Install

Download the **`astrabridge_runner-…-py3-none-any.whl`** file from
[GitHub Releases](https://github.com/incident201/AstraBridgeForOpenMW/releases/latest).
The same wheel works on Linux and Windows.

**A `.whl` is a Python installation package, not a program to double-click or
unpack.** Installing it creates the `astrabridge-runner` command.
You do not need the source archive or a copy of this repository.

Create a folder named, for example, `AstraBridgeRunner`. Put the downloaded
wheel there and **open a terminal in that folder**. Use this folder for all
examples below.

The examples use `astrabridge_runner-0.1.7-py3-none-any.whl`.
**Substitute the exact filename you downloaded.**

### Linux — Bash

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ./astrabridge_runner-0.1.7-py3-none-any.whl
astrabridge-runner --help
```

If Python or `venv` is missing, install it through your distribution's package
manager. On Debian/Ubuntu, install `python3-venv` and `python3-pip`. Do not use
`sudo pip`.

### Windows — PowerShell

Install Python 3.11 or newer first, then run:

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\astrabridge_runner-0.1.7-py3-none-any.whl
$env:Path = "$(Resolve-Path .\.venv\Scripts);$env:Path"
astrabridge-runner --help
```

If your Python installation has `python` but not `py`, replace `py -3` with
`python`. The PATH line makes the command available in this PowerShell window
without changing script execution policy.

### Each time you open a new terminal

Return to your `AstraBridgeRunner` folder and run:

Linux:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
$env:Path = "$(Resolve-Path .\.venv\Scripts);$env:Path"
```

You only install once. This step makes the installed command available again.
The `.venv` folder contains the runner and its Python dependencies.

## 2. Update or uninstall

### Update

Stop the runner. Download the new wheel into the same folder and install it
in the same environment. Replace `VERSION` below with the downloaded version.

Linux, after activating the environment:

```bash
python -m pip install --upgrade ./astrabridge_runner-VERSION-py3-none-any.whl
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade .\astrabridge_runner-VERSION-py3-none-any.whl
```

This updates the runner. Update AstraBridge Desktop and its runtime separately
through the application's normal update process.

### Uninstall

Stop the runner first. If you signed in with ChatGPT and want to disconnect that
account, run `astrabridge-runner auth logout` before uninstalling.

Linux, with the environment activated:

```bash
python -m pip uninstall astrabridge-runner
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip uninstall astrabridge-runner
```

Alternatively, deleting the `.venv` folder removes this dedicated Python
environment and everything installed in it. You can also delete the downloaded
wheel and exported `api-skill` folder if no longer needed.

**Keep `sessions` if you want to retain conversation logs and screenshots.**
Deleting runner files does not remove the AstraBridge application, game profiles,
game saves or MP4 recordings. ChatGPT credential storage is separate; see the
[technical reference](agent-runner-reference.md#chatgpt-accounts-and-credentials)
if you also want to remove its saved registration files.

## 3. Prepare AstraBridge

1. Open AstraBridge Desktop and complete game/runtime setup.
2. In **Setup → Storage and skill**, choose **Enable CLI command**. Follow any
   PATH instructions, then reopen your terminal if needed. Repeat the runner's
   activation/PATH step in the new terminal.
3. Check the game's command:

   ```sh
   astrabridge version
   ```

4. Export the runner's gameplay instructions:

   ```sh
   astrabridge skill export ./api-skill --interface tools
   ```

This creates the `api-skill` folder. The runner reads it automatically; you do
not install it into Codex or any other agent application.

`astrabridge` is the **game application's** command.
`astrabridge-runner` is the **model runner's** command.

The export destination must not already exist. Keep `--interface tools`:
ordinary CLI skill exports are not the runner edition.

If you do not enable the short `astrabridge` command, export by running the
AppImage/EXE directly instead. Use your actual path:

```bash
"/path/to/AstraBridge.AppImage" skill export ./api-skill --interface tools
```

```powershell
& "C:\path\to\astrabridge.exe" skill export ./api-skill --interface tools
```

You can reuse this export when switching game profiles. After a game application
update that changes the skill, export to a new folder and use that folder for
new runner sessions.

## 4. Sign in or enter an API key

Choose **one** provider:

| Provider | How to connect | API-key variable |
| --- | --- | --- |
| OpenAI | Sign in with ChatGPT (OAuth) | Not needed |
| Google Gemini | Gemini API key | `GEMINI_API_KEY` |
| xAI Grok | xAI API key | `XAI_API_KEY` |
| DeepSeek | DeepSeek API key | `DEEPSEEK_API_KEY` |
| Xiaomi MiMo | MiMo API key | `MIMO_API_KEY` |

### OpenAI — Sign in with ChatGPT

```sh
astrabridge-runner auth login
astrabridge-runner auth status
```

The first command opens a browser. Sign in and grant access. The runner saves
and refreshes your credentials; you do not log in before every session.

This uses the selected ChatGPT account's available plan limits, subject to
account/workspace access. It does not require an OpenAI API key and does not
fall back to API-balance billing if plan access is unavailable.

**No browser on the runner computer?** Use:

```sh
astrabridge-runner auth login --no-browser
```

Open the printed link on another computer. After sign-in, the browser may show
an error loading a `127.0.0.1` address. Copy that complete address and paste it
into the waiting runner terminal. Keep the login command running while you do
this; the terminal hides the pasted address.

### Gemini, Grok, DeepSeek or MiMo — API key

Get a key from your provider's developer account. API access and billing are
separate from simply signing into its consumer chat application.

The following example uses Gemini. **For Grok, DeepSeek or MiMo, replace
`GEMINI_API_KEY` with the variable from the table.**

Linux — Bash:

```bash
read -r -s -p "API key: " GEMINI_API_KEY
printf '\n'
export GEMINI_API_KEY
```

Windows PowerShell:

```powershell
$key = Read-Host "API key" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new("", $key).Password
Remove-Variable key
```

Paste the key at the prompt. These commands hide it and keep its literal value
out of command history. The key is available to the runner in **this terminal**;
set it again after opening another terminal. Do not put it in the task prompt.

## 5. Choose a model and start

List the models available to your account:

```sh
astrabridge-runner models --provider openai
```

Replace `openai` with `gemini`, `grok`, `deepseek` or `mimo` for another provider.
The list shows model IDs and reasoning levels. Use the exact model ID, not
its display name.

In AstraBridge Desktop, **select the intended profile and click Start game**.
Leave the main menu open for a new game, or load the save you want to continue.
Release manual control and disconnect any other agent. You can leave the viewer
open to watch.

Run **one** of these examples from your runner folder. They work in Bash and
PowerShell after setup:

**OpenAI — GPT-6 Luna:**

```sh
astrabridge-runner run --provider openai --model gpt-6-luna --reasoning low --skill ./api-skill --log-dir ./sessions
```

**Gemini 3.8 Flash:**

```sh
astrabridge-runner run --provider gemini --model gemini-3.8-flash --reasoning low --skill ./api-skill --log-dir ./sessions
```

**Grok 4.7:**

```sh
astrabridge-runner run --provider grok --model grok-4.7 --reasoning low --skill ./api-skill --log-dir ./sessions
```

**DeepSeek 4.1 Flash:**

```sh
astrabridge-runner run --provider deepseek --model deepseek-flash --reasoning low --skill ./api-skill --log-dir ./sessions
```

**MiMo V2.6 Pro:**

```sh
astrabridge-runner run --provider mimo --model mimo-v2.6-pro --reasoning high --skill ./api-skill --log-dir ./sessions
```

Set `MIMO_API_KEY` first, as described above. MiMo currently treats every
reasoning level except `none` as the same enabled thinking mode. Use
`--reasoning none` to disable thinking; `low` does not reduce its intensity.

To choose another model, replace `--model` and `--reasoning` with supported values
from the model list. Reasoning effort controls reasoning according to the
provider's supported modes; it is **not a spending limit**. See
[model observations](Models.md) for gameplay results.

`--skill` points to the exported folder. `--log-dir` selects where conversations
are stored. The runner prints the connected profile and a **Session directory**
when it starts; keep that path for resuming later.

## 6. Give the model a task

When you see **`Task>` in the terminal**, type your prompt and press Enter.
For example:

```text
Start a new game, complete the tutorial, then find Caius Cosades in Balmora. Save your progress when you reach him.
```

For a game you have already loaded:

```text
Continue from the current game. Read the journal to understand the active quest, then work toward its objective. Save when you have made useful progress.
```

The runner does not automatically start a new game or load a save. Do that in
Desktop first, or explicitly ask the model to do it.

Tools and screenshots are passed to the model automatically. When it returns
a final text answer without a tool call, `Task>` appears again. Type another
instruction to continue the same conversation.

To provide the first prompt directly in the launch command, append:

```text
--task "Your goal here"
```

Watch the game in Desktop. To record, start recording there before connecting
the runner, or ask the model to manage recording. Videos go to Desktop's
configured recordings folder; runner conversations go to `./sessions`.

## 7. Stop and resume

| What you want | What to do |
| --- | --- |
| Stop the model while it is working | Press **Ctrl+C** in its terminal. |
| Exit at `Task>` | Type `/quit`. |
| Save before leaving | Ask the model to save and wait for the result before stopping it. |
| Save, finish recording and stop the game | Use **Stop session** in Desktop. It asks before stopping without a save if saving is unavailable. |

Stopping the runner releases its control and normally leaves the game paused.
It **does not automatically save the game or finish recording**.

To continue later, select the same profile, start the game and restore the game
state you want to continue from. Activate the runner in your terminal and set
your API key again if using one. Then:

```sh
astrabridge-runner resume "./sessions/SESSION_DIRECTORY"
```

Replace `SESSION_DIRECTORY` with the actual directory printed by the earlier
run, not the parent `sessions` folder. This resumes model work immediately.
To supply a new instruction:

```sh
astrabridge-runner resume "./sessions/SESSION_DIRECTORY" --task "Continue toward the objective, then save."
```

**Resume restores the conversation, not a game save.** If you loaded an older
save or played manually in between, explain what changed in `--task`.

An existing conversation stays tied to its model, settings, installation,
profile and skill. To switch models/profiles or use changed skill text, start a
new `run`. Game saves, atlas and knowledge remain part of the game profile.

DeepSeek conversations created with the old Chat Completions adapter cannot
resume in runner 0.1.4 or later. Start a new runner conversation in the same
game profile to continue playing.

## 8. Logs, usage and common problems

The terminal shows token usage after API requests. To inspect a saved session:

```sh
astrabridge-runner logs stats "./sessions/SESSION_DIRECTORY"
```

Add `--json` for machine-readable statistics. No model request is made.

| Counter | Meaning |
| --- | --- |
| `in` | Input tokens, including history and image tokens reported by the API. |
| `cache` / `uncached` | Input reused from the provider cache / input not served from cache. |
| `out` | Generated tokens, including reasoning. |
| `reasoning` | The reasoning portion of output; do not add it again. |
| `total` | Input plus output. |
| `cache hit` | Cached share of input where counters are available. |
| `Context: ~…` | Estimated current context size, not cumulative session usage. |

`?` means the provider did not report a counter. Cache hits are automatic and
not guaranteed. Check your provider account for actual charges or plan limits.

Long conversations are summarized automatically into **checkpoints**. These
are model memories, not game saves. Recent images stay in active context;
older images and the complete conversation remain in the session archive.
Token totals survive both summarization and resume.

### Remove old logs

Preview deletion of inactive archives older than 30 days, keeping the five
newest sessions:

```sh
astrabridge-runner logs prune --log-dir ./sessions
```

Add `--delete` to apply it:

```sh
astrabridge-runner logs prune --log-dir ./sessions --delete
```

This deletes the selected conversations, their screenshots and resume state.
It does not delete game saves or MP4 recordings. Active sessions are skipped.

### Common problems

| Problem | What to do |
| --- | --- |
| `astrabridge-runner` is not found | Return to your runner folder and repeat the activation/PATH step. |
| `astrabridge` is not found | Enable the application's CLI command in Setup, or export using the AppImage/EXE directly. |
| `pip` cannot find the wheel | Check the filename and working folder, or use the wheel's full quoted path. |
| Skill destination already exists | Export to a new directory and use it in `--skill`. |
| Wrong skill interface | Export with `--interface tools`. |
| Application/runtime mismatch | Complete the runtime update in Desktop, then export again. |
| Controller is busy | Release manual control or disconnect the other agent in Desktop. |
| Game is not running | Start it in Desktop. |
| Missing or unauthorized API key | Set the right environment variable in the launching terminal and check the key in your provider account. |
| ChatGPT login succeeds but model access is denied | Check `auth status`, model availability and the selected account/workspace's limits. |
| Unsupported model or reasoning level | Check `models --provider …` and use supported values. |
| Resume reports a different profile or changed skill | Select the original profile/skill, or start a new conversation. |

For optional settings, multiple accounts and technical details, see the
[runner reference](agent-runner-reference.md).
