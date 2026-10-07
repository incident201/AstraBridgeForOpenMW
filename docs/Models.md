# Model Results

This document summarizes practical results from running different AI models with AstraBridge.

These results describe how the models behave specifically when playing Morrowind through AstraBridge. They should not be treated as a general ranking of the models.

## GPT models

All tests of Astra, Sol, and Luna were run through Codex CLI as the harness on Linux.

All three models handle context compaction well: they retain the current goal and continue working after compaction. Tests with longer context windows did not produce a visible improvement in quality.

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

**Poor results.**

Tests were run through the Codex harness.

The default integration was unusable for these tests. Because of the API's handling of image context, every request had to resend all images the model had previously viewed.

A local proxy was introduced for testing. It removed older images from API requests, keeping only a few recent screenshots. Older images remained available to the model on request, as before.

With this setup, the model frequently hallucinated and invented strange explanations for its mistakes. It was reluctant to read AstraBridge responses in full and often discarded useful information from them.

It also tended to write unhelpful automation scripts for route finding. These attempts often led to walking in circles and showed severe spatial disorientation.

## Grok 4.7

Tests were run through Grok Build as the harness on Linux.

The model receives game screenshots but, for an unknown reason, refuses to open or inspect them. It also tends to repeat "observe" requests unnecessarily and fails to establish a stable observation-action loop.

This is likely a harness issue, although the cause has not been confirmed.

A possible solution is to use the Grok API directly. This has not been tested yet because it would require an additional adapter specifically for Grok.

## Claude

Opus 5.5 and Sonnet 5.5 were tested through Claude CLI.

Both models behaved very similarly. They showed clear navigation difficulties even during the tutorial, struggled to keep track of passages, and repeatedly returned to the same places.

They also frequently truncated AstraBridge responses and discarded useful information in the process.

Further testing is needed to understand the causes of these problems.
