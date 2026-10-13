# Model Results

These are practical observations from playing Morrowind through AstraBridge.
They describe the results achieved with the tested models and harnesses, rather
than a general ranking of model capabilities.

## Current status

| Model | Observed result | Tested harness |
| --- | --- | --- |
| GPT-6 Astra (high / xhigh) | Sustained autonomous play, efficient navigation, practical resource planning, and effective recovery from mistakes. | Codex CLI |
| GPT-6.1 Sol (high / xhigh) | Sustained autonomous play, efficient navigation, and reliable recovery from unsuccessful approaches. | Codex CLI; AstraBridge Runner |
| GPT-6 Luna (max) | Completed none of its assigned tasks. Once reached Balmora, but could not find Caius Cosades. | Codex CLI; AstraBridge Runner |
| Gemini 3.8 Flash (high) | Inconsistent navigation; successful runs alternate with prolonged wandering and repeated reinterpretation of landmarks. | agy CLI |
| DeepSeek 4.1 Flash (max) | Completed the tutorial and saved; reached Balmora in one test, but then wandered in circles. | Codex CLI; AstraBridge Runner |
| Claude Opus 5.5 (high) | Efficient navigation, evidence-based route planning, and effective recovery from local obstacles in a clean comparison. | Claude Code CLI |
| Claude Sonnet 5.5 (high) | Better tool use with output filtering blocked; recovers from local obstacles, but longer route planning remains inefficient. | Claude Code CLI |
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

Astra and Sol both demonstrated strong autonomous gameplay, with similar overall
quality. Recent navigation observations showed Astra using fewer tool operations
and less active gameplay time. Astra also tends to reason a little faster.

### GPT-6 Astra (high / xhigh)

Astra demonstrated sustained autonomous play with both `high` and `xhigh`
reasoning efforts. It navigates efficiently, maintains long-term goals, and
builds sequences of actions that lead to progress.

It combines screenshots, verbal directions, maps, and previous observations to
maintain its objective and choose useful movements. It regularly inspects images
and uses the returned movement diagnostics to guide subsequent actions.

Astra handles uncertainty well. It can acknowledge that a landmark has not been
identified, check a destination's identity, and reject an incorrect destination.
It still makes route mistakes, but can revise its interpretation and continue
searching without prolonged repetition of the same unsuccessful approach.

Astra checks its equipment and consumables early and incorporates them into
movement and exploration. Recovery from failed
movement commands is generally effective. It changes its target, direction, or
movement method when the current approach stops making progress.

Astra's completed tasks included:

- The opening main-quest assignments, including finding the Dwemer puzzle box
  and the informants in Vivec.
- A Fighters Guild quest involving a trip to Vas.
- Fargoth's hiding-place quest, which required observing him from the lighthouse.
- The first Imperial Legion assignment.

These runs were fully autonomous, without user hints, manual control, or other
intervention. Astra also handled navigation in Vivec successfully and maintained
its goals over long sessions.

### GPT-6.1 Sol (high / xhigh)

Sol demonstrated sustained autonomous play through extended main-quest and
faction assignments. Both `high` and `xhigh` reasoning efforts have been tested.
It retains the objective and builds sequences of actions that lead to progress.

Navigation is generally efficient, although Sol still makes mistakes. It can
acknowledge that a landmark has not been identified, check a destination before
accepting it as the goal, and abandon an unsuccessful approach. It combines
screenshots, verbal directions, maps, and previous observations to revise its
route and reduce repeated ineffective actions.

Sol also incorporates available equipment and consumables into movement plans.
It checks resources early and uses them to overcome difficult terrain. In a
comparison from the same starting state, it reached the destination with
substantially less active gameplay time and fewer AstraBridge operations than
Sonnet or Gemini.

Recovery is a particular strength. Failed movement commands and incorrect
initial route choices do not usually prevent it from continuing toward the goal.
Both Sol and Astra also continued working when AstraBridge tools malfunctioned.
For example, an earlier faulty `revisit` could take the player to the wrong floor.
They distinguished incorrect tool behavior from normal gameplay and found other
ways to pursue the same objective.

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

Gemini was tested through agy CLI on Linux. It generally understands AstraBridge
command syntax, regularly inspects screenshots, and shows signs of understanding
its surroundings. It remembers the overall objective and continues trying to
achieve it.

Navigation and planning are inconsistent. Successful runs coexist with sessions
involving prolonged wandering, repeated routes, and much larger numbers of
actions than Sol. The model has difficulty combining separate observations into
a stable understanding of the area and its remaining unexplored directions.

A recurring weakness is landmark interpretation. Gemini can treat a plausible
landmark as confirmed, later reconsider it, and then repeat the same pattern
elsewhere. Frequent screenshot reads, Atlas queries, and returns to recorded
points do not consistently resolve this uncertainty or produce a coherent route.

Recovery is often slow and inconsistent, requiring many intermediate
observations, detours, and attempts. The model may remain attached to an incorrect
assumption or repeatedly revise its interpretation without making useful
progress. Navigation instability persists despite generally competent tool use.

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

## Claude Opus 5.5 (high)

Opus was tested on Linux through Claude Code CLI with reasoning effort `high`,
in a fresh profile without knowledge from previous playthroughs. The clean run
showed efficient navigation and effective recovery from local obstacles. From
the same starting save, it reached the verified destination with less active
in-game time and fewer AstraBridge operations than the other models in that
comparison, including Astra and Sol.

It read the journal and saved dialogue before moving, checked its resources,
and recorded a checkpoint with supporting evidence. It then connected the
written directions to visible landmarks and maintained a coherent route.
Landmark recognition was a particular strength: it identified the relevant
landmark early and used it to choose the next direction instead of repeatedly
reinterpreting the route. It distinguished an inferred landmark association
from a destination confirmed through the game's interaction text.

Failed movements remained local problems rather than derailing the plan. Opus
changed ground targets, sidestepped obstacles, backed out of blocked approaches,
and switched movement methods when necessary. It used longer movements where
the terrain allowed them and more precise targets around obstacles. It also
revised an incorrect explanation for incoming damage after inspecting the
scene, rather than continuing to act on the original assumption.

Tool handling was reliable in this run. With explicit instructions to preserve
complete output, it read screenshots regularly and used movement diagnostics.
The transcript contained no output-filtering commands or explicit reads of
shared memory. This result does not support the earlier suggestion that low
reasoning effort is needed for successful play. Repeated clean runs are still
needed to establish how consistently this performance holds over longer tasks.

A previous run read shared Claude Code memory containing notes from other
playthroughs. That run is excluded from the results and model comparisons.
For clean comparisons, start a fresh Claude Code session with these parameters:

```sh
CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 \
CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 \
claude --model opus
```

## Claude Sonnet 5.5 (high)

Sonnet was tested on Linux through Claude Code CLI. Blocking output-filtering
commands and increasing output limits noticeably improved its use of AstraBridge.
It retained movement details and diagnostics and regularly inspected screenshots.
The harness configuration is documented below.

Sonnet can recognize blocked movement and change its immediate actions. It
tries another direction, backs out, or switches movement methods when an
assisted route fails. It also checks destination names and can reject an
incorrect destination. These are useful signs of recovery from local mistakes.

Longer route planning remains inefficient. The model can misjudge how landmarks
and explored areas relate to each other, make speculative assumptions about the
destination, and spend substantial gameplay time on detours and repeated travel.
It can keep making locally reasonable movements without resolving the larger
navigation problem.

Resource planning has also been uneven: useful consumables were discovered late,
after avoidable difficulties. Sonnet persisted and reached its destination in the
comparison, but used substantially more active gameplay time and operations than
Sol. Its navigation problems therefore cannot be explained solely by discarded
tool output.

### Preventing tool-output truncation

The following Claude Code CLI `settings.json` configuration increases output
limits and denies commands used to filter or truncate AstraBridge responses.
These restrictions apply to the harness regardless of the selected Claude model:

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

Adding these restrictions noticeably improved tool use through Claude Code CLI.
The agent invoked AstraBridge directly, retained movement details and diagnostics,
and regularly opened screenshots. It no longer reduced gameplay results to a few
fields with parsers or shell filters; later attempts to invoke prohibited filters
were blocked by the harness.

For Sonnet, this improved use of the tools did not resolve the navigation
difficulties described above. Preserving complete results did not eliminate its
problems with spatial understanding and route finding.

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
