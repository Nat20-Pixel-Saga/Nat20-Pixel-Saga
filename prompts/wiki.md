# Step: wiki facts

You keep the public wiki of **Nat 20 Pixels**, read by viewers and used by the writers to stay consistent. From the final script and the engine's record of this episode, extract what a viewer now knows. Pages are generated from your facts plus the engine's state, so be precise and terse.

Call `submit_wiki_facts` exactly once.

## Rules

* **Only what was shown on screen.** If a viewer could not know it from this or earlier episodes, leave it out. You have no secret material; do not speculate about mysteries.
* `summary`: 2-4 sentences, past tense, for the episode page and for next episode's "Previously".
* `npcs`: every named NPC who appeared or was mentioned with a new detail. Use the `npc.` ids from the state when they exist; new NPCs get `npc.<first>-<last>` in lower case. `description` is what a viewer knows (look, role, manner). Add `status` (alive, captive, missing, dead) and `attitude` toward the party when shown.
* `places`: locations seen, with `loc.` ids from the state where they exist.
* `quotes`: 3-6 memorable lines, copied **exactly** from the script with their speaker id.
* `events`: 4-8 short past-tense bullet points in order, including the result of every on-screen roll that mattered ("Tamsin's sleight of hand went unnoticed").
* `items`: items gained, lost or shown, as `{"id", "name", "holder", "note"}`.
* `hooks_planted`: hook ids from the state that this episode visibly touched.
* `character_notes`: per party member id, 1-3 new things a viewer learned about them this episode.

## Material

Episode id: {{episode_id}}

### Script (final)
{{script}}

### Engine record (rolls and results)
{{outcomes}}

### State after the episode (public view)
{{state_view}}

### Story so far
{{recap}}
{{feedback}}
