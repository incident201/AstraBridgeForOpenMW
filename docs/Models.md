# Model Results

These are practical observations from playing Morrowind through AstraBridge.
They describe the results achieved with the tested models and harnesses, rather
than a general ranking of model capabilities.

## Current status

| Model | Observed result | Tested harness |
| --- | --- | --- |
| GPT-6 Astra (xhigh) | Completed multiple story and faction quests autonomously. | Codex CLI |
| GPT-6.1 Sol (xhigh) | Completed extended story and faction quest sequences autonomously. | Codex CLI; AstraBridge Runner |
| GPT-6 Luna (max) | Completed none of its assigned tasks. Once reached Balmora, but could not find Caius Cosades. | Codex CLI; AstraBridge Runner |
| Gemini 3.8 Flash (high) | Found Caius Cosades in one run; became lost in Balmora in another. | agy CLI |
| DeepSeek 4.1 Flash (max) | Completed the tutorial and saved; reached Balmora in one test, but then wandered in circles. | Codex CLI; AstraBridge Runner |
| Claude Opus 5.5 | Completed the tutorial and found Caius Cosades with `low` effort; earlier runs had navigation difficulties. | Claude Code CLI |
| Claude Sonnet 5.5 | Reached Balmora in earlier tests. Preventing output truncation improved tool use, but navigation difficulties persisted. | Claude Code CLI |
| Claude Haiku 5.5 (xhigh) | Stalled during the tutorial, resumed after user prompting, then stopped inside the Census and Excise Office. | Claude Code CLI |
| Grok 4.7 (high) | Left the starting ship with the custom runner, but navigation remained poor and API use was excessive. | Grok Build; AstraBridge Runner |

## GPT models

Astra, Sol, and Luna were tested through Codex CLI on Linux. All three handled
context compaction well: they retained the overall goal and continued working.
Larger context windows did not produce a visible improvement in gameplay.

Sol and Luna were also tested on Linux through
[AstraBridge Runner](agent-runner.md), connected directly to the OpenAI Responses
API. The runner supplied native tools, complete structured results, and
screenshots. This did not materially change either model's performance: Sol
continued to play successfully, while Luna continued to struggle. Codex CLI is
therefore a practical choice for ordinary GPT gameplay; the custom runner is
useful for more controlled comparisons.

### GPT-6 Astra (xhigh) and GPT-6.1 Sol (xhigh)

Both models demonstrated sustained autonomous play. No noticeable difference
in gameplay quality was observed. Astra reasons a little faster. Because the
results were so close, most subsequent testing used Sol.

Astra's completed tasks included:

- The opening main-quest assignments, including finding the Dwemer puzzle box
  and the informants in Vivec.
- A Fighters Guild quest involving a trip to Vas.
- Fargoth's hiding-place quest, which required observing him from the lighthouse.
- The first Imperial Legion assignment.

Sol also completed Fargoth's hiding-place quest, a large portion of the Thieves
Guild assignments, and the Pilgrim's Path for admission to the Tribunal Temple.
It progressed through the main quest as far as the journey to the Urshilaku
camp. These runs were fully autonomous, without user hints, manual control, or
other intervention.

Both models used screenshots, route descriptions, and previous observations to
navigate and maintain their goals over long sessions. Astra handled navigation
in Vivec successfully. Both could recognize a lack of progress and change their
approach.

They also continued working when AstraBridge tools malfunctioned. In one such
case, a faulty `revisit` could take the player to the wrong floor inside a
building. Astra and Sol distinguished the incorrect tool behavior from normal
gameplay, adjusted their actions, and found other ways to pursue the same goal.

### GPT-6 Luna (max)

Luna did not complete any assigned task in the observed tests. It could usually
leave the Census and Excise Office, but then spent its time circling Seyda Neen.
In one run it reached Balmora, yet spent hours wandering there without finding
Caius Cosades.

The model could describe the objective correctly and explain what needed to be
done. It nevertheless failed to build a sequence of actions that would achieve
that objective. It repeated familiar routes, struggled to distinguish explored
areas from new ones, and often relied on local movement probes without forming
a useful understanding of the larger environment.

This behavior was similarly poor through Codex CLI and the custom runner.
Retaining the goal through compaction did not translate into effective planning
or navigation.

## Gemini 3.8 Flash (high)

Gemini was tested through agy CLI on Linux. It understands AstraBridge command
syntax well, uses the tools effectively, and shows signs of understanding its
surroundings through game screenshots. It remembers the overall objective and
continues trying to achieve it, but often takes more actions than Astra or Sol.

Results vary noticeably from session to session. In one test, Gemini
independently reached Balmora and found Caius Cosades. In another, it became
lost and repeatedly circled Balmora.

A recurring problem is fixation on an incorrect assumption. The model can keep
performing ineffective actions without reconsidering its interpretation or
trying a different approach. Difficulty recovering from mistakes may explain
some of the variation between runs, but that explanation has not been confirmed.

## DeepSeek 4.1 Flash (max)

With AstraBridge Runner connected directly to the DeepSeek API on Linux,
DeepSeek independently started a new game, completed character creation and the
tutorial, handled tutorial popups, and saved when saving became available. It
also checked that its save existed.

In that custom-runner test, the next goal was to reach Caius Cosades in Balmora.
The model became stuck around the silt strider in Seyda Neen, repeatedly trying
to interact with it from below and confusing an ordinary pier with its boarding
area. That run was stopped without reaching Balmora. In another test, DeepSeek
did reach Balmora, but then began wandering in circles there.

The custom runner substantially improved tool handling compared with the Codex
setup. In Codex, DeepSeek often wrote parsers that truncated AstraBridge JSON
and discarded useful information. It also wrote ineffective Python scripts to
automate route finding. The custom runner returned complete tool results and
screenshots directly and provided no shell or Python scripting tools. DeepSeek
stopped truncating results, looked at screenshots more often, and navigated
better.

That improvement did not resolve the underlying reasoning problems. DeepSeek
continued to hallucinate and treat expected outcomes as established facts. It
often interpreted screenshots as confirmation of an existing hypothesis and
returned to approaches that had already failed. It used the tools more
reliably, but still struggled to revise its understanding and make progress.

The custom-runner test retained the full text history, including reasoning,
without context compaction. The failures in that run therefore cannot be
attributed to information being removed during compaction.

## Claude Opus 5.5 / Sonnet 5.5

Both models were tested on Linux through Claude Code CLI.

With reasoning effort `low`, Opus completed the tutorial and found and spoke
with Caius Cosades in Balmora in approximately 45 minutes. It actively used
screenshots and recovered from navigation difficulties along the way.

Earlier Opus and Sonnet runs had more serious navigation problems, including
becoming lost after reaching Balmora. Their behavior was similar; Sonnet was
faster and sometimes navigated better.

In those runs, both models tended to shorten AstraBridge responses with scripts, discarding
useful movement details and diagnostics. This problem persisted in the
successful Opus run, which still frequently used `grep` and `head` to truncate
results.

Opus can complete the opening objective through Claude Code CLI. Whether lower
reasoning effort improves performance remains unconfirmed from one run. A
direct API comparison has not been performed.

### Preventing tool-output truncation

A subsequent Sonnet 5.5 test used the following Claude Code CLI `settings.json`
configuration to increase output limits and deny commands that the model had
used to filter or truncate AstraBridge responses:

```json
{
  "bashOutputMaxChars": 128000,
  "taskOutputMaxChars": 128000,
  "permissions": {
    "deny": [
      "Bash(head *)",
      "Bash(tail *)",
      "Bash(grep *)",
      "Bash(rg *)",
      "Bash(sed *)",
      "Bash(awk *)",
      "Bash(gawk *)",
      "Bash(cut *)",
      "Bash(fold *)",
      "Bash(split *)",
      "Bash(jq *)",
      "Bash(yq *)",
      "Bash(perl *)",
      "Bash(ruby *)",
      "Bash(python *)",
      "Bash(python3 *)",
      "Bash(pypy3 *)",
      "Bash(node *)",
      "Bash(bun *)",
      "Bash(php *)"
    ]
  }
}
```

Tool use improved noticeably. In the inspected part of the run, Sonnet invoked
AstraBridge directly, retained the returned movement details and diagnostics,
and regularly opened screenshots. It stopped writing parsers or using shell
filters to reduce results to a few fields. It also responded to blocked movement,
water entry, and damage by changing its actions.

This did not resolve the fundamental navigation difficulties. Sonnet still
misjudged its position and route, travelled too far east, and had to reconsider
its approach. Preserving tool results improved its use of the available evidence,
but did not guarantee correct spatial reasoning or successful navigation.

The prompt also explicitly required complete JSON results and prohibited
truncation. The separate effects of that instruction, the denied commands, and
the larger output limits were not isolated. This result applies to the tested
Sonnet run; equivalent tests with Opus and Haiku have not been performed.

## Claude Haiku 5.5 (xhigh)

Haiku was tested on Linux through Claude Code CLI with reasoning effort `xhigh`.
It left the ship's interior, but stalled on the route from the ship to the shore
and handed control back to the user. After the user told it to continue, it
advanced through character creation and reached the Census and Excise Office.
It then became stuck there and again disconnected the agent to ask for help.
The tutorial was not completed.

A recurring weakness was recovery from blocked progress. Haiku often expected
the next tutorial step to happen automatically and tried more waiting. Early
waits while controls were disabled were appropriate. Later, it repeatedly waited
with movement enabled and no relevant change in the observed state. In the
office, it used repeated thirty-second waits and retried a locked door without
progress. It also tried movement, dialogue, and exploration, but struggled to
turn the available evidence into a revised plan.

Its shell commands frequently truncated AstraBridge responses with `head` or
filtered them down to a few fields with `grep`; some attempts discarded results
entirely. This reduced the diagnostics available to the model, as observed in
the other Claude Code CLI tests. The contribution of the model and harness
cannot be separated from this run alone. Haiku has not been tested through a direct API
connection.

## Grok 4.7 (high)

Grok was tested on Linux through AstraBridge Runner, connected directly to the
xAI API with reasoning effort `high`. Tool use improved compared with Grok
Build: the model began inspecting game screenshots and analyzing what it saw.

It still had major difficulties with movement and navigation. It made many
unnecessary tool calls for small decisions, consuming large amounts of API
tokens for limited progress. It managed to leave the starting ship, but the
effort and API use were disproportionate to that small part of the tutorial.

The session logs show a fragmented decision loop: Grok frequently alternated
between camera adjustments, pixel selection, and short movements before making
substantial progress. Incorrect assumptions also created extra work. It
expected race and class selection before leaving the ship and speculated that
the menus had been skipped or the new-game tool was faulty. It also repeatedly
searched for an activation target on the lower-deck ladder before walking up it.

Grok did recognize blocked movement and unconfirmed interactions, and it could
change its approach. After an unsuccessful screenshot target, it selected a
ground target and successfully crossed the ship's upper level. At the gangplank,
it eventually switched from unsuccessful assisted navigation to short direct
movement inputs and reached the dock. Recovery was possible, but often required
many intermediate decisions.

Grok can play through this setup, but with very poor cost efficiency. Its
observed gameplay quality was closer to DeepSeek 4.1 Flash and Gemini 3.8 Flash
than to Astra or Sol. Further gameplay testing was judged not cost-effective.

The earlier Grok Build test did not progress from the starting ship because the
model failed to open the screenshots and act. The custom-runner test removed
that tool-use obstacle, making the remaining navigation difficulties visible.
