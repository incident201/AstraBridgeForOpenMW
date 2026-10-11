# Model Results

This document summarizes practical results from playing Morrowind through
AstraBridge with different AI models. The assessments apply to these gameplay
tests and their harness configurations; they are not a general model ranking.

## Current status

| Model | Status | Recommended harness |
| --- | --- | --- |
| GPT-6 Astra | Great. Fully playable. | Codex CLI |
| GPT-6.1 Sol | Great. Fully playable. | Codex CLI |
| GPT-6 Luna | Very bad. Playable. | Codex CLI |
| Gemini 3.8 Flash | Mediocre. Playable. | agy CLI |
| Grok 4.7 | Not playable. | N/A |
| DeepSeek 4.1 Flash | Bad. Playable. | [astrabridge-runner](agent-runner.md) |
| Claude (Opus 5.5 / Sonnet 5.5) | Mediocre. Playable. | Claude CLI |

## Results by model

### GPT-6 Astra (xhigh)

**Test setup:** Codex CLI on Linux.

#### Observed behavior

Astra navigates well, keeps track of explored areas and unknown directions,
and handles verbal route descriptions reliably. It retains long-term goals
over extended sessions and uses AstraBridge controls as intended.

It currently provides the best and most consistent results among the tested
models.

#### Consistency and recovery

When an approach fails to produce progress, Astra can recognize the problem
and try a different strategy. It also continued working toward its goals when
AstraBridge itself had clear bugs or malfunctioning tools.

For example, in early versions, a broken `revisit` could take the player to the
wrong floor inside a building. Astra distinguished this tool failure from
normal gameplay, found a workaround, and continued toward the original goal.

### GPT-6.1 Sol (xhigh)

**Test setup:** Codex CLI and AstraBridge Runner on Linux, with the latter
connected directly to the OpenAI Responses API.

#### Observed behavior

Sol combines screenshots, previous observations, and route information into
a reasonably consistent understanding of its surroundings. It handles AstraBridge
controls reliably and maintains long-term goals. Its navigation and actual
gameplay progress are close to Astra's.

#### Consistency and recovery

Sol continued making progress despite clear AstraBridge errors, including
`revisit` taking the player to the wrong floor. It recognized the incorrect
tool behavior and adjusted its actions to pursue the same goal through other
means.

#### Limitations

Sol sometimes spends more time reasoning before taking an action. This did
not produce a significant difference in actual gameplay progress compared
with Astra in the observed runs.

### GPT-6 Luna (max)

**Test setup:** Codex CLI and AstraBridge Runner on Linux, with the latter
connected directly to the OpenAI Responses API.

#### Observed behavior

Luna generally understands AstraBridge commands and remembers the overall
objective. It often uses local movement probes to test directions, but
struggles to connect visual observations with the results of its actions.

#### Consistency and recovery

It repeatedly returns to explored routes and has difficulty distinguishing
known areas from new ones, even when the atlas provides that information.
These navigation problems also occurred with the custom runner.

#### Limitations

Remembering and describing the goal does not reliably translate into
successful navigation. Building a larger spatial understanding from
screenshots remains a major weakness, including during the opening tutorial.

### Gemini 3.8 Flash (high)

**Test setup:** agy CLI on Linux.

#### Observed behavior

Gemini understands AstraBridge command syntax very well and uses the tools
effectively. It shows signs of understanding its surroundings through game
screenshots.

The agent remembers the overall objective and continues trying to achieve it,
but often takes more actions than frontier models such as Astra.

#### Consistency and recovery

Its performance varies noticeably between sessions compared with the other
tested models. In some runs, it completes the tutorial reasonably well,
reaches Balmora, and finds Caius Cosades. In others, it gets stuck walking in
circles inside the Census and Excise Office or around Seyda Neen.

Gemini sometimes becomes fixated on an incorrect assumption and keeps taking
ineffective actions without reconsidering that assumption or changing its
approach. Difficulty recovering from errors is a possible explanation for
the uneven results; this connection has not been confirmed.

#### Limitations

It has difficulty combining separate observations into a stable
representation of the environment and often repeats routes it has already
taken.

### DeepSeek 4.1 Flash (max)

**Test setup:** AstraBridge Runner on Linux, connected directly to the
DeepSeek API. Earlier Codex tests are covered in the harness observations
below.

#### Observed behavior

With the custom runner, DeepSeek read complete AstraBridge JSON results and
used tools more reliably. It examined screenshots more often and navigation
improved compared with the Codex tests.

It independently started a new game, completed character creation and the
opening tutorial, handled tutorial popups, and saved successfully when saving
became available. It also checked that its save existed.

#### Consistency and recovery

The next task was to reach Caius Cosades in Balmora. The model spent roughly
27 minutes circling the silt strider in Seyda Neen, repeatedly trying to
interact with it from below and confusing an ordinary pier with its boarding
area. The run was stopped without reaching Balmora.

It repeatedly claimed to understand the layout while returning to approaches
that had already failed. Revising an incorrect explanation and changing
strategy remain major weaknesses.

#### Limitations

The improved tool use did not fundamentally raise gameplay quality. DeepSeek
still tends to treat an expected outcome as an established fact and interpret
screenshots as confirmation of its current hypothesis. It does not
consistently use visual observations as the source of truth for building and
checking its understanding of the surroundings.

These failures occurred with the full conversation retained and no context
compaction. Information removed during compaction therefore does not explain
the failures in this run.

### Grok 4.7

**Test setup:** Grok Build on Linux.

#### Observed behavior

The model receives game screenshots but, for an unknown reason, refuses to
open or inspect them. It also repeats `observe` requests unnecessarily and
fails to connect visual observations with the results of its actions.

#### Consistency and recovery

It did not establish a stable observation-action loop in the tested setup.
This prevented useful gameplay.

#### Limitations

The cause remains unresolved. Harness behavior is a suspected explanation;
direct API testing is needed to separate it from model limitations.

### Claude Opus 5.5 / Sonnet 5.5

**Test setup:** Claude CLI, testing both Opus 5.5 and Sonnet 5.5.

#### Observed behavior

Both models behaved very similarly. They showed navigation difficulties
already during the tutorial, struggled to keep track of passages, and
repeatedly returned to the same places.

#### Consistency and recovery

The repeated navigation problems were accompanied by frequent truncation of
AstraBridge responses. The models discarded useful information in the process.

#### Limitations

The contribution of the harness to these problems has not been established.
Direct API tests are needed before drawing conclusions about the models
independently of Claude CLI.

## Harness observations

### GPT: Codex CLI and AstraBridge Runner

Astra, Sol, and Luna all handled context compaction well in Codex CLI: they
retained their goals and continued working after compaction. Longer context
windows did not produce a visible improvement in quality.

Sol (xhigh) and Luna (max) were also tested through AstraBridge Runner using
the OpenAI Responses API directly. The runner presented AstraBridge controls
as native tools, returned complete structured results, and supplied
screenshots automatically.

The harness change did not produce a meaningful difference in gameplay
quality. Luna still struggled with navigation and repeated familiar routes;
Sol continued to navigate and progress without significant difficulty.

Codex CLI is therefore a practical harness for ordinary GPT gameplay through
AstraBridge. The custom runner is useful for more controlled experimental
comparisons between models.

### DeepSeek: Codex and the custom runner

The default Codex integration was unusable because DeepSeek's API required
every request to resend all previously viewed images. For those tests, a
local proxy removed older images from requests, keeping only a few recent
screenshots. Older images remained available on request.

In that setup, DeepSeek frequently hallucinated and invented unusual
explanations for its mistakes. It truncated AstraBridge JSON through its own
output-processing wrappers and wrote unhelpful Python scripts for route
finding, often walking in circles with severe spatial disorientation.

The custom runner presented AstraBridge controls as native tools, returned
complete JSON results, and supplied screenshots automatically. API requests
included only the latest selected image; older images remained available on
request. The full text history, including reasoning, was retained without
compaction. The model had no shell or Python scripting tools.

DeepSeek stopped truncating responses and used tools more reliably. Removing
the option to write ineffective automation scripts had a positive effect:
it more often examined screenshots and tried to navigate from what it saw.
These changes improved tool handling, but the navigation
and error-recovery problems described above remained.

### Grok and Claude: suspected harness issues

The screenshot problem in Grok Build and the difficulties observed through
Claude CLI may be caused by characteristics of those harnesses. This is a
working hypothesis, not a confirmed diagnosis.

Neither setup has been compared with a direct API run. Grok API testing was
deferred because it requires an additional provider adapter. Direct API tests
of Opus 5.5 and Sonnet 5.5 have also not been conducted.
