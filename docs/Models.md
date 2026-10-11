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
| Claude Opus 5.5 / Sonnet 5.5 | Reached Balmora in CLI testing, but navigation suffered from discarded tool diagnostics. | Claude CLI |
| Grok 4.7 | Did not begin playing on the starting ship; the harness setup was unusable. | Grok Build |

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

Both models were tested through Claude CLI and behaved very similarly. Sonnet
was faster and sometimes navigated better than Opus. These observations apply
to the tested CLI setup; they do not establish how the models would compare
through a direct API connection.

The Claude tests included reaching Balmora, but navigation then broke down.
A recurring problem was the models' tendency to write their own parsers that
reduced AstraBridge's JSON output to a simple success/failure flag. This removed
useful movement details and diagnostics. Without that information, the models
struggled to understand what had happened and repeated the same requests.

The leading explanation is that the emphasis on coding in the models' behavior
within Claude CLI encourages output processing that is poorly suited to
embodied tasks. A similar tool-handling problem occurred with DeepSeek through
Codex and disappeared after the switch to a custom runner. This gives a reason
to investigate the harness, but a direct API comparison is still needed to
establish its effect on Claude. That comparison has not been performed.

## Grok 4.7

Grok was tested through Grok Build on Linux. It did not begin playing on the
starting ship: it failed to open and inspect the game screenshots and did not
proceed with gameplay actions.

The tested Grok Build setup was unusable for this task. It prevented a meaningful
assessment of Grok's navigation or ability to complete game objectives. A direct
API test is needed before drawing conclusions about the model's gameplay
capabilities. That test has not been conducted.
