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
| Gemini 4 Argon (medium / high) | Efficient navigation and effective local recovery, with high response latency even for routine actions. | AstraBridge Runner |
| Gemini 3.8 Flash (high) | Inconsistent navigation; successful runs alternate with prolonged wandering and repeated reinterpretation of landmarks. | agy CLI |
| MiMo V2.6 Pro (high) | Follows quest directions and recovers from local blocks, but navigation is uneven and API responses are slow. | AstraBridge Runner |
| DeepSeek 4.1 Flash (max) | Completed the tutorial and saved; reached Balmora in one test, but then wandered in circles. | Codex CLI; AstraBridge Runner |
| Claude Opus 5.5 (high) | Can navigate autonomously and recover from mistakes, but route planning is uneven and can involve substantial detours. | Claude Code CLI |
| Claude Sonnet 5.5 (high) | Recovers from local obstacles, but longer route planning remains inefficient. | Claude Code CLI |
| Claude Haiku 5.5 (xhigh) | Poor recovery from blocked progress; tends to wait or ask for help instead of revising its plan. | Claude Code CLI |
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
Sonnet or Gemini 3.8 Flash.

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

## Gemini models

### Gemini 4 Argon (medium / high)

Argon was tested on Linux through AstraBridge Runner, connected directly to the
Gemini API, with `medium` and `high` reasoning efforts.

Navigation has been efficient in the observed tasks. Argon connects verbal
directions with screenshots and recognizable landmarks, follows a coherent
route, and retains its intended direction after going around obstacles. It can
use substantial movements where appropriate instead of relying entirely on
small exploratory steps.

Recovery from local difficulties is a strength. When movement is blocked or a
target is lost, Argon changes direction or switches control methods and continues
toward the objective. It also continued after an AstraBridge tool error by
checking the resulting view and adjusting its actions.

Tool and UI use is generally reliable. Argon handled character creation and
tutorial prompts autonomously, responding to interruptions without abandoning
the task. It considers the overall objective when choosing character abilities
and checks available resources before travel. Occasional incomplete tool calls,
extra camera adjustments and retracing still occur.

High response latency is a significant practical weakness. Long waits occur
even before routine menu selections and other simple actions. Efficient use of
active gameplay time therefore does not necessarily translate into fast progress
in real time. These delays measure the full API response in the tested setup,
including processing and transport.

The observations support promising navigation and local recovery, but do not yet
establish sustained success across long, varied quest sequences. The different
tasks do not provide a controlled comparison of `medium` and `high` effort.

### Gemini 3.8 Flash (high)

Flash was tested through agy CLI on Linux. It generally understands AstraBridge
command syntax, regularly inspects screenshots, and shows signs of understanding
its surroundings. It remembers the overall objective and continues trying to
achieve it.

Navigation and planning are inconsistent. Successful runs coexist with sessions
involving prolonged wandering, repeated routes, and much larger numbers of
actions than Sol. The model has difficulty combining separate observations into
a stable understanding of the area and its remaining unexplored directions.

A recurring weakness is landmark interpretation. Flash can treat a plausible
landmark as confirmed, later reconsider it, and then repeat the same pattern
elsewhere. Frequent screenshot reads, Atlas queries, and returns to recorded
points do not consistently resolve this uncertainty or produce a coherent route.

Recovery is often slow and inconsistent, requiring many intermediate
observations, detours, and attempts. The model may remain attached to an incorrect
assumption or repeatedly revise its interpretation without making useful
progress. Navigation instability persists despite generally competent tool use.

## MiMo V2.6 Pro (high)

MiMo was tested on Linux through AstraBridge Runner, connected directly to the
MiMo API using Chat Completions with thinking enabled.

It reads journal entries and dialogue directions, retains the objective, and
uses signpost labels, screenshots and maps to make progress. It followed the
directions as far as the destination's entrance and handled an intervening fight
using the returned health and target-state information.

Longer route planning is uneven. MiMo can lose a useful road, spend many actions
among obstacles, and repeatedly reinterpret the same distant landmarks without
establishing a better route. Detailed visual descriptions do not consistently
produce reliable spatial understanding. Some interpretations are plainly wrong,
including mistaking a HUD element for a possible landmark in the game world.

Recovery is possible, but often slow. MiMo recognizes lack of progress, changes
movement methods, consults the Atlas and returns to known landmarks. It can
eventually abandon an unproductive approach and resume useful travel. However,
it may repeatedly reconsider alternatives before committing to an action, and
its explanations for failed movement are not always verified.

High response latency is a significant practical weakness. API responses often
take **30–60 seconds**, sometimes longer, including before small movement or
other routine actions. Repeated deliberation adds substantial delay without
necessarily improving the decision. These are full API response times in the
tested setup, not isolated measurements of reasoning time.

The observations show useful autonomous navigation and recovery, but do not yet
establish reliable completion of longer quests.

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

## Claude models

Opus, Sonnet, and Haiku were tested through Claude Code CLI on Linux. The harness
settings below apply to all three models. Model-specific observations follow;
reliable tool handling does not by itself imply reliable navigation.

### Shared harness configuration

Claude Code's shared memory can carry knowledge between playthroughs. Disable
automatic memory and CLAUDE.md loading when starting an independent session.
Replace `MODEL` with `opus`, `sonnet`, or `haiku`:

```sh
CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 \
CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 \
claude --model MODEL
```

In `settings.json`, increase output limits and deny commands used to filter or
truncate AstraBridge responses:

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

Also instruct the agent to preserve complete tool responses, including movement
diagnostics, rather than reduce them to success/failure or discard output.
These settings and instructions address a recurring tool-use problem: shell
filters and custom parsers remove information the model needs to understand
what happened. Blocking those commands noticeably improved tool use, but did
not eliminate navigation difficulties.

### Claude Opus 5.5 (high)

Opus can retain its goal, navigate autonomously, and recover from unsuccessful
approaches. Route planning is uneven: it can follow a short, direct route, but
can also spend substantial time on detours and repeated travel.

With explicit instructions to preserve complete responses, tool use is generally
reliable. Opus reads quest directions, regularly views screenshots, consults maps
and the Atlas, and uses movement diagnostics. Navigation difficulties persist
even when it retains the full tool output.

A weakness is connecting landmarks and map observations into a reliable route.
When a landmark is missing or uncertain, Opus can make increasingly specific
estimates of the destination's position without confirming the reference point.
Repeated observation and returns to familiar locations do not always resolve
that uncertainty quickly.

Recovery is a useful strength. Opus changes movement targets and methods, backs
away from blocked terrain, and uses known points to retrace its route. It checks
destination identities, rejects incorrect destinations, and records failed
approaches in its checkpoint. It can abandon an unsuccessful search strategy
and continue toward the goal, although this may require considerable extra
movement and tool use.

### Claude Sonnet 5.5 (high)

Sonnet retains movement details and diagnostics and regularly inspects
screenshots with output filtering blocked.

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

### Claude Haiku 5.5 (xhigh)

Haiku struggles to turn observations into useful actions when progress is blocked.
It tends to wait for the situation to resolve itself, even when movement is
available and nothing in the observed state suggests that waiting will help.
It can attempt movement, dialogue, and exploration, but has difficulty combining
the results into a revised plan.

Autonomous persistence is also weak. Haiku stopped and asked for help during the
tutorial, resumed after user prompting, and then stalled again. It did not
complete the tutorial.

Tool-output truncation also reduced the diagnostics available to Haiku. This is
the same harness-level issue addressed by the shared configuration above.

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
