# Repository instructions

## Keep documentation current

- Every change to OpenMW engine code, including native adapters and the engine
  patch recipe in `harness/native/`, must include corresponding updates to
  [docs/openmw-modifications.md](docs/openmw-modifications.md) and any other
  affected documentation in `docs/`. Explicitly describe what changed, why it
  changed and which engine files or components are affected. Keep the inventory
  consistent with the implementation.
- When adding or changing a bundled mod or gameplay fix, update the relevant
  section of [docs/mods-and-fixes.md](docs/mods-and-fixes.md). Explain its purpose,
  behavior and integration, including configuration and compatibility details
  where applicable. Remove or correct obsolete descriptions when a component
  is removed or replaced.
- Make these documentation updates as part of the same change as the code or
  mod they describe.

## Keep the gameplay skill accurate

- When the public CLI changes, update the affected usage instructions in
  [skill/SKILL.md](skill/SKILL.md) and its `skill/references/` documents. Cover
  changed commands, options, output fields and behavior so an agent can use the
  interface correctly.
- Preserve the skill's purpose: playing Morrowind through AstraBridge. Interface
  changes require updates to operational instructions, not a rewrite of the
  skill's identity or general description.
- Do not change the skill's descriptive metadata or introductory purpose text
  unless the user explicitly requests it. This includes the frontmatter
  `description` in `skill/SKILL.md` and the display name, short description and
  default prompt in `skill/agents/openai.yaml`.

## Keep the root README focused

- [README.md](README.md) is for the basic project overview, installation and
  general setup instructions.
- Do not add changelogs, development history, investigation notes or unnecessary
  implementation details to the root README. Put human/developer explanations
  in the appropriate `docs/` document and agent usage instructions in the skill.
  Use concise links from the README where needed.
