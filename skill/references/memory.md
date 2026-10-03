# Working state, tasks and evidence

Use this when writing or resuming the current task, or attaching durable notes to observed objects. All commands follow `astrabridge game`.

## Notes about one object

Every safely matched visible instance has a `memory_ref`, even before you know its
name. Copy that value to attach notes, tasks or conversation reminders to that
particular NPC, creature, door or item. In these commands replace `OBJECT_REF` and
`NOTE_REF` with actual returned handles:

```sh
astrabridge game knowledge add --kind note --object-ref OBJECT_REF --text "Door on the left of the stairs; inspect later"
astrabridge game knowledge add --kind conversation --object-ref OBJECT_REF --text "Ask about the missing ring"
astrabridge game knowledge list --object-ref OBJECT_REF
astrabridge game knowledge update --ref NOTE_REF --status done
astrabridge game knowledge objects --query "Fargoth"
astrabridge game knowledge objects --object-ref OBJECT_REF
```

The catalog contains only previously encountered instances in the active atlas
profile. It reports remembered names/types and note counts; it supplies no current
position, visibility or lock state. The same note remains attached when a new
observation gives the object a different `visible_…` ref. Two similarly named
objects have separate memory refs and notes. When the object is visible again,
match its `memory_ref` in the new observation and use that row's `ref` for actions.

Notes are agent-written observations or hypotheses; adding a name in note text
does not teach the bridge that name. Use `--kind fact` only with the existing
observed-evidence/quote requirements below. Object notes follow the atlas profile
across older saves and restarts, and remain readable while the object is out of sight.

## Persistent tasks and evidence

Memory persists in the active Desktop profile, alongside the retained Atlas. Use these public commands; do not access the database directly during gameplay:

```sh
astrabridge game knowledge add --kind task --text "Current objective and next step"
astrabridge game knowledge add --kind conversation --text "Unfinished conversation and what to ask next"
astrabridge game knowledge list --status open --query "TEXT"
astrabridge game knowledge update --ref NOTE_REF --status done
astrabridge game knowledge evidence --query "TEXT"
astrabridge game knowledge evidence --ref EVIDENCE_REF --offset 0 --limit 4000
astrabridge game knowledge add --kind fact --text "My summary" --evidence EVIDENCE_REF --quote "Exact supporting passage"
astrabridge game knowledge events --page 0 --limit 20
```

`evidence_ref` identifies text already returned by dialogue, journal inspection or reading an opened document. It remains readable after the menu closes or the controller restarts. Fact summaries require a real evidence ref and an exact nonempty quote from it. They remain agent-written summaries; the quote supports review rather than certifying every inference. Tasks/conversation notes are explicitly agent notes. Status can be `open`, `done` or `abandoned`.

New inventory quantities, journal changes and effect start/end events are preserved separately from transient messages. An `event_id` can be found again through `knowledge events`. Repeated observations do not recreate the same change. Loading an earlier save resets change comparisons: old memory remains historical and is not proof of current ownership or quest state. Notes and evidence are not automatically injected into observations; query them on resume and when needed. Previously recognized instance names are supplied automatically as described above.

## Current working state

`knowledge checkpoint 'JSON'` atomically replaces one current checkpoint in the
active Atlas playthrough namespace, inside this Desktop profile's database.
`knowledge brief` retrieves it without advancing time, taking a screenshot or
querying hidden game state. This is an agent-written plan and recollection, not
a bridge-generated quest solution or a guarantee that the goal is complete.

```sh
astrabridge game knowledge checkpoint '{"goal":"Find the house described in the conversation","next_step":"Inspect the remaining doors beside the last verified landmark","status":"open","evidence_refs":[],"note_refs":[],"object_refs":[],"place_refs":[],"failed_attempts":["Repeating the same short circuit did not reveal another door"]}'
astrabridge game knowledge brief
```

Write only what actually happened; the example is a format template. Prefer
references to real evidence and known places over copying entire conversations.
All checkpoints require `goal` and `next_step` strings (up to 2000 characters
each). `status` is `open` by default, or `done`/`abandoned`; `next_step` may be empty
for a closed goal. Each reference list allows at most eight distinct entries;
`failed_attempts` allows up to eight nonempty strings of at most 600 characters.
The normalized JSON payload must fit in 8192 UTF-8 bytes. Unknown fields are rejected.

Reference fields accept only existing memory:

| Field | Get the values from |
|---|---|
| `evidence_refs` | `evidence_ref` on observed dialogue, journal or documents, or `knowledge evidence` |
| `note_refs` | `ref` from `knowledge add/list` |
| `object_refs` | An object's persistent `memory_ref`, or `knowledge objects` |
| `place_refs` | Persistent `node_…` refs from `atlas`, or `place_…` notes from `remember`/`recall` |

Transient visible, item, UI, movement and save handles are rejected in these
lists. Do not put them in the text either: reacquire live handles from a fresh
observation. Notes about an object must belong to the active Atlas namespace;
place notes from a previous branch need a retained Atlas-node association.
A node is a remembered place, not a promise that the current route is unobstructed.

The write response contains `working_memory` with `available`, `revision` and
`needs_revalidation`. The same small pointer appears in normal observations and
in `agent connect`; the checkpoint's goal/text is not repeatedly injected.
With no checkpoint, it reports `available:false` and brief returns `checkpoint:null`.

`brief` returns the checkpoint, current `branch`, `checkpoint_branch`, update
time and short linked records under `references.evidence/notes/objects/places`.
Reference text previews are limited to 160 characters. Read full evidence with
`knowledge evidence --ref ...`; read full notes with `knowledge list` (query by
note ref if needed). Links that are no longer available are explicitly marked
`unavailable:true`. The brief never opens old screenshots or resolves a memory
ref into a live target by itself.

After **any** save load, the continuation branch changes. Earlier checkpoints
remain readable with `needs_revalidation:true` and a reason such as `load`.
Old task notes may still say `done`; they are historical agent conclusions,
not proof of current inventory, door state or quest progress. Reading brief
changes nothing. Verify the relevant conditions through gameplay and write a
new checkpoint to acknowledge the new branch. Use a new request ID for that
write; replaying an old receipt does not update the checkpoint.

A new game uses a fresh Atlas namespace with no checkpoint; loading the earlier
playthrough can recover its checkpoint. New Desktop profiles have independent
empty storage. Explicit profile duplication copies checkpoints and other memory
once; the copies then evolve independently. Runtime restarts preserve stored
memory, but the agent still needs a fresh observation and live handles.

## Resume after context loss

1. Check `status` for an active operation. Read its `action-result` before issuing
   another mutation; a checkpoint never determines whether a pending action succeeded.
2. Once idle, run `knowledge brief`. Recover the goal, next step, evidence and
   unsuccessful approaches. If absent, use the user's objective and existing notes.
3. Obtain a fresh observation. If revalidation is required, check relevant public
   journal/dialogue/inventory/world information before relying on remembered progress.
4. Continue or revise the approach. Replace the checkpoint at meaningful milestones,
   when changing strategy and before `finish-session`/handoff. The bridge does not
   invent or automatically rewrite these decisions.
