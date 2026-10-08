# Model Results

This document summarizes practical results from running different AI models with AstraBridge.

These results describe how the models behave specifically when playing Morrowind through AstraBridge. They should not be treated as a general ranking of the models.

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

## GPT models

Initial tests of Astra, Sol, and Luna were run through Codex CLI as the harness on Linux.

All three models handle context compaction well: they retain the current goal and continue working after compaction. Tests with longer context windows did not produce a visible improvement in quality.

### Harness comparison

GPT-6.1 Sol (xhigh) and GPT-6 Luna (max) were also tested on Linux through AstraBridge's own runner, connected directly to the OpenAI Responses API. The runner presented AstraBridge controls as native tools, returned complete structured results, and supplied screenshots automatically.

These tests did not show a meaningful difference in gameplay quality compared with Codex CLI. Luna continued to struggle with navigation and repeat familiar routes, even in the opening tutorial. Sol continued to navigate and progress through the tutorial without significant difficulty.

These results support using Codex CLI as a suitable harness for GPT models playing through AstraBridge. The custom runner is primarily useful for more controlled experimental comparisons between models; Codex CLI remains a practical choice for ordinary play.

### GPT-6 Astra (xhigh)

**Excellent results.**

Astra is very good at spatial navigation. It can keep track of which areas have already been explored and which directions are still unknown.

It handles verbal route descriptions well and can remember long-term goals over extended sessions. When an approach is not working, it can recognize the lack of progress and try a different strategy instead of repeating the same actions.

It also understands AstraBridge control commands reliably and generally uses the available tools as intended.

Overall, Astra currently provides the best and most consistent results.

### GPT-6.1 Sol (xhigh)

**Very close to Astra.**

Sol shows almost the same level of navigation, spatial understanding, and long-term planning.

It can use screenshots, previous observations, and route information to maintain a reasonably consistent understanding of the environment. It also handles AstraBridge controls without significant problems.

Sol sometimes spends more time reasoning before taking an action, but in terms of actual in-game progress it performs at roughly the same level as Astra.

### GPT-6 Luna (max)

**Understands the controls, but has major navigation problems.**

Luna generally understands AstraBridge commands, but has difficulty connecting visual information with the results of its own actions.

It frequently repeats routes it has already explored and often fails to distinguish known areas from new ones, even when this information is available in the atlas.

Instead of relying on screenshots and building a larger mental map of the environment, Luna often prefers local movement probes to test possible directions.

It usually remembers and can describe the overall objective, but has great difficulty turning that objective into successful navigation.

## Gemini 3.8 Flash (high)

**Better than Luna in practice, but still far behind the frontier models.**

Tests were run through agy CLI as the harness on Linux.

Gemini understands AstraBridge command syntax very well and uses the available tools effectively.

It shows signs of understanding its surroundings through game screenshots. However, it still has difficulty combining separate observations into a stable representation of the environment. As a result, it often repeats routes it has already taken.

The agent remembers the overall objective and can achieve it, but often needs more actions than frontier models such as Astra.

## DeepSeek 4.1 Flash (max)

**Tool use improved; overall results remain poor.**

### Earlier Codex tests

Earlier tests were run through the Codex harness. The default integration was unusable because every request resent all previously viewed images. A local proxy removed older images from API requests, keeping only a few recent screenshots. Older images remained available on request.

With this setup, DeepSeek frequently hallucinated and invented strange explanations for its mistakes. It often truncated AstraBridge JSON responses through its own output-processing wrappers, discarding useful information. It also wrote unhelpful Python automation scripts for route finding, repeatedly walked in circles, and showed severe spatial disorientation.

### Custom harness test

A follow-up test was run on Linux through a minimal custom harness connected directly to the DeepSeek API. AstraBridge controls were presented as native tools. The harness returned complete structured JSON results and supplied screenshots automatically. Only the latest selected image was included in API requests; older images remained available on request. The full text history, including reasoning, was retained without context compaction. The model had no shell or Python scripting tools.

DeepSeek stopped truncating AstraBridge JSON output and used tools more reliably. Navigation improved overall compared with the Codex tests. Removing the ability to write ineffective Python automation scripts had a positive effect: the model more often examined screenshots and tried to orient itself in the game world.

It independently started a new game, completed character creation and the opening tutorial, and saved successfully when saving became available. It handled tutorial popups and checked that its save existed.

The next task was to reach Caius Cosades in Balmora. The model spent roughly 27 minutes circling the silt strider in Seyda Neen, repeatedly trying to interact with it from below and confusing an ordinary pier with its boarding area. The run was stopped without reaching Balmora.

These improvements did not fundamentally raise the quality of play. DeepSeek still tends to treat an expected outcome as an established fact. It interprets screenshots as confirmation of its current hypothesis and does not consistently use them as the source of truth for building and testing an understanding of its surroundings.

It repeatedly claimed to understand the layout while returning to approaches that had already failed. Revising an incorrect explanation and choosing a different strategy remain major weaknesses. These failures occurred with the full conversation preserved and no compaction, so they cannot be explained by information being removed during compaction in this test.

## Grok 4.7

Tests were run through Grok Build as the harness on Linux.

The model receives game screenshots but, for an unknown reason, refuses to open or inspect them. It also tends to repeat "observe" requests unnecessarily and fails to establish a stable observation-action loop.

This is likely a harness issue, although the cause has not been confirmed.

A possible solution is to use the Grok API directly. This has not been tested yet because it would require an additional adapter specifically for Grok.

## Claude

Opus 5.5 and Sonnet 5.5 were tested through Claude CLI.

Both models behaved very similarly. They showed clear navigation difficulties even during the tutorial, struggled to keep track of passages, and repeatedly returned to the same places.

They also frequently truncated AstraBridge responses and discarded useful information in the process.

As with Grok, these problems are likely to be caused by characteristics of the harness itself, although this has not been confirmed.

To isolate the models' behavior from harness effects, they need to be tested directly through the API. Such tests have not been conducted yet.
