# UI, dialogue and services

Use these commands for an open menu, conversation, book or service. For a popup that interrupts an action, see [onboarding](onboarding.md#modals-during-an-action). All commands follow `astrabridge game`.

## Menus and dialogue

| Syntax | Arguments and behavior |
|---|---|
| `trigger NAME` | Exact allowed names: `Activate`, `ToggleWeapon`, `ToggleSpell`, `Jump`, `Inventory`, `Journal`, `GameMenu`, `Rest`. Toggle names toggle state; check current stance/menu first. |
| `map` | Open the game's regular Map window. Use `map local` / `map world` for the large view; see [maps](maps.md). This is distinct from `atlas`. |
| `choose UI_REF` | Invoke an enabled control in the currently open menu, including list rows outside the viewport. |
| `choose "EXACT_CAPTION"` | Resolve a current caption. Prefer a ref for ambiguity; same-caption buttons are preferred over other control types. |
| `edit UI_REF "TEXT"` | Replace a visible input's contents, up to 1000 characters. It does not press its confirmation button. |
| `adjust UI_REF N` | Set a slider to integer position N, within its reported `slider_max`. This is a position, not an assumed percentage. |
| `hover UI_REF` | Move the cursor onto a current UI element and observe its normal tooltip. Requires an open UI. |
| `scroll N --observation OBS` | Scroll under the native UI cursor: −10…10 integer steps, negative = down. Hover the intended region first. |
| `click X Y --button B --observation OBS` | Pixels from the current 720p screenshot; B=1/2/3 (left/middle/right), default 1. |
| `key KEY --observation OBS` | Allowed: `escape`, `enter`, `tab`, `space`, `up`, `down`, `left`, `right`, `backspace`, `delete`, `pageup`, `pagedown`. No arbitrary keys/chords. |
| `text "TEXT" --observation OBS` | Type 1…160 characters, no control characters, into the currently focused UI field. Prefer `edit` for identified inputs. |

Use named gameplay commands instead of raw clicks/keys for movement. For mouse/keyboard fallbacks, obtain a current observation first; another `observe` makes its earlier number stale. Structured `choose/edit/adjust/hover` use refs and **do not take** `--observation`.

UI roles: `button`, `link`, `list_item`, `input`, `slider`, `item`, `item_slot`, `drop_target`, `text`. Respect `enabled` and modals. Check `selected` after choosing a list row. All currently populated list rows are available independently of scrolling: dialogue topics/services, item views and ordinary selection lists. The default response is paginated; use search or `ui --full` for all rows. Full dialogue data include `ui.dialogue.topics` and `ui.elements`. Use `choose` directly; scrolling is unnecessary. `details ui` and `ui --full` contain the complete displayed conversation history; compact previews report truncation. Responses to unselected topics are not exposed. `screen_visible:false` entries have no `rect` and cannot be hovered or clicked by coordinates, but can be chosen by ref. Close tutorial messages through their actual controls before retrying an interaction that did not execute.

**Dialogue:** approach/interact with a visible NPC → inspect `ui` → choose an actual topic/reply ref → read the new text → choose the game's farewell control when finished. Do not assume the window closed just because a reply was selected.

**Trading/containers:** inspect `panel` to distinguish `inventory`, `merchant`, and `container`. Choosing an item may open a quantity dialog or begin a drag. Resolve the actual dialog, then choose the destination `drop_target` if a drag is active. `pending_trade` means a proposal; use the merchant's real confirmation button and verify ownership/gold afterward. Closed-container contents are not exposed.

**Service shortcuts:**

- `rest HOURS [--seconds 30]` opens the ordinary rest/wait menu, sets its hours slider, confirms, and reports the actual game hours passed. Legal rest/wait restrictions and interruptions still apply.
- `buy "EXACT_ITEM_NAME" --quantity N --max-total GOLD [--instance INSTANCE] [--seconds 30]` requires an open barter menu with an empty proposal. It chooses the quantity, checks the actual quoted total, submits one offer, then verifies ownership and gold. A price/funds limit cancels the proposal through the real cancel button; an unconfirmed/rejected offer is not repeated.
- `travel "EXACT_DESTINATION" [--max-cost GOLD] [--seconds 30]` requires the open travel menu. It uses that menu's structured destination and price, then verifies location change and payment. It does not infer destinations from remembered names.

The service `seconds` limit bounds waiting for UI completion in wall time. A sequence's simulation deadline and damage guard also apply. These shortcuts use ordinary game callbacks; they do not bypass costs or requirements.

Current UI rows expose stable controls when applicable: `service_barter`, `service_travel`, `service_repair`, `service_training`, `service_spells`, `service_spellmaking`, `service_enchanting`, `service_persuasion`, `service_companion`; `rest_hours`, `rest_confirm`, `rest_cancel`; `quantity_slider`, `quantity_value`, `quantity_confirm`, `quantity_cancel`; `trade_offer`, `trade_cancel`, `trade_balance`; `travel_destination`. IDs are identical in Russian, English and other translations. Captions remain in the game's language. Numeric service quotes use `value`; travel rows also include `destination`.

**Spellmaking, enchanting, alchemy, training, level-up and character creation:** use ordinary UI operations on the controls actually displayed.

### Books, scrolls and manual repair

Open an owned book with `use-item`, or a book in the world with `interact`. `ui.document` reports its title, kind, ref and total character count. Use `read` for consecutive chunks, `read --search "TEXT"` for relevant excerpts, or `read --all` when the whole text is needed. For bounded replies, call `read` and continue with `read --ref DOCUMENT_REF --offset NEXT_OFFSET` until `eof:true`. Offsets count Unicode characters, not UTF-8 bytes. The text covers the whole opened document; observations carry metadata only, so long books do not overflow replies. The ref also works after turning pages. Closing/reopening the book invalidates it. `document_not_open` means no book/scroll is open; `stale_document_ref` requires a new query. Images remain available in the screenshot.

Use an owned repair hammer to open Repair. `ui.elements` includes the actual repairable rows as `role:item`, `panel:repair`, with `condition_current`, `condition_max` and the normal tooltip. Rows outside the viewport can be chosen semantically. Choosing one performs **one normal repair attempt**, consuming tool use and applying the game's skill/RNG rules. Refresh the UI after every attempt; failure is possible, and fully repaired items disappear. The `repair tool: …` slot shows the selected hammer and opens the game's tool selector when chosen. `repair "EXACT_ITEM_NAME" --attempts N --condition-pct P` repeats these normal attempts with fresh refs, stopping at the requested percentage, exhausted attempts, a changed menu, ambiguity or cancellation. Defaults are one attempt and 100%. Each attempt reports before/after condition when the row remains; fully repaired rows disappear. For identical names, pass `--instance INSTANCE` from inventory or repair rows. The helper never guesses; a removed/merged instance requires a fresh selection.
