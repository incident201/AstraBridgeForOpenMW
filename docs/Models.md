# Model Results

This document summarizes practical results from running different AI models with AstraBridge.

These results describe how the models behave specifically when playing Morrowind through AstraBridge. They should not be treated as a general ranking of the models.

## GPT-6 Astra (xhigh)

**Excellent results.**

Astra is very good at spatial navigation. It can keep track of which areas have already been explored and which directions are still unknown.

It handles verbal route descriptions well and can remember long-term goals over extended sessions. When an approach is not working, it can recognize the lack of progress and try a different strategy instead of repeating the same actions.

It also understands AstraBridge control commands reliably and generally uses the available tools as intended.

Overall, Astra currently provides the best and most consistent results.

## GPT-6.1 Sol (xhigh)

**Very close to Astra.**

Sol shows almost the same level of navigation, spatial understanding, and long-term planning.

It can use screenshots, previous observations, and route information to maintain a reasonably consistent understanding of the environment. It also handles AstraBridge controls without significant problems.

Sol sometimes spends more time reasoning before taking an action, but in terms of actual in-game progress it performs at roughly the same level as Astra.

## GPT-6 Luna (max)

**Understands the controls, but has major navigation problems.**

Luna generally understands AstraBridge commands, but has difficulty connecting visual information with the results of its own actions.

It frequently repeats routes it has already explored and often fails to distinguish known areas from new ones, even when this information is available in the atlas.

Instead of relying on screenshots and building a larger mental map of the environment, Luna often prefers local movement probes to test possible directions.

It usually remembers and can describe the overall objective, but has great difficulty turning that objective into successful navigation.

## Gemini 3.8 Flash (high)

**Better than Luna in practice, but still far behind the frontier models.**

Gemini sometimes has problems understanding how individual AstraBridge controls should be used.

It actively uses screenshots for navigation, but has difficulty combining separate observations into a stable representation of the environment. As a result, it often repeats routes it has already taken.

Gemini also tends to perform very large numbers of small movements and micro-actions without much clear progress.

It usually remembers the global objective, but often reaches its destination through brute-force exploration rather than deliberate navigation and planning.

Despite these problems, it has performed better than Luna in the current tests.

## DeepSeek 4.1 Flash (max)

**Poor fit for AstraBridge in its current form.**

DeepSeek's stateless API requires previous screenshots and other context to be repeatedly sent back with new requests. During long gameplay sessions this causes the request context to grow very quickly.

To keep the session running, AstraBridge has to use aggressive context compaction. This regularly causes what can effectively be described as compaction amnesia: information that was previously established is lost or no longer connected correctly with new observations.

DeepSeek also has difficulty linking what it currently sees with previously verified facts. It may forget NPC names, confuse characters it has already met, or lose track of its current location.

Because of the combination of context growth and information loss after compaction, DeepSeek 4.1 Flash is currently not recommended for AstraBridge.

## Grok 4.7

**Testing is still in progress. Early results are poor.**

In the first tests, Grok has had serious problems establishing a stable observation-action loop.

It tends to repeat "observe" requests unnecessarily and often fails to connect visual observations with the results of its previous actions.

The main problem currently looks like a broken control loop rather than simple navigation difficulty. Grok does not appear to use the AstraBridge skill correctly or consistently in its current form.

More testing is required to determine whether this is a model limitation, a skill compatibility issue, or something specific to the current integration.

## Claude

Claude models have not been tested yet.
