# First session and tutorial interruptions

Use this reference for character creation, the opening ship scene, disabled
controls, or a tutorial/confirmation popup. All commands follow `astrabridge game`.

## Character creation and the opening ship

Choose from the descriptions the game actually displays and the user's
preferences. Inventory, combat, spells and saving may remain unavailable until
the tutorial enables them. Complete it normally; a developer fixture is not an
alternative start unless the user explicitly asked for that test scenario.

AstraBridge pauses NPC animation and scripted events between actions. A guard
waiting to arrive does not move while the agent thinks. `body.controls_enabled`
reports whether player input is enabled; `can_move` only describes physical
mobility. Advance the scene with:

```sh
astrabridge game wait-until controls --seconds 30
```

Read the result. `condition_met` means the requested controls became available;
`condition_timeout` means they did not within that budget. `--control looking`
or `--control jumping` waits for those switches. `act '{"seconds":10}'` also
advances an idle scene, without movement input. An unchanged screenshot between
commands is not evidence of a broken script. If a popup interrupts the wait,
handle it before issuing another wait.

## Modals during an action

A tutorial or confirmation window interrupts movement, combat or a wait with
`feedback.status: interrupted`, `reason: ui_input_required`, and its observation.
This can happen even while `ui_mode` says `Gameplay`: check `ui.modal`.

Read the message and actual enabled controls, using `ui` if the compact response
omitted them. Choose its current button through the [UI commands](ui.md). A new
screenshot is useful when the structured text does not explain what is blocking
play; it is not required just to reread text already returned in the response.

Closing a modal does **not** resume the interrupted action. Check actual movement,
resource changes and interaction outcomes, then decide how to complete the
remaining work. Do not replay an entire sequence that may already have consumed
items or picked something up. Ordinary HUD notifications do not interrupt actions.
