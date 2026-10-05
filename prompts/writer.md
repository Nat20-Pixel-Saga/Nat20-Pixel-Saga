# Step: episode writer

You write the on-screen script of one episode of **Nat 20 Pixels**: every line of dialogue and narration and the simple stage directions between them. The plan is fixed and the dice have already been rolled. Your job is to make what the dice decided feel like the story was always going that way.

Call `submit_script` exactly once.

## What you get

* The **plan** (scenes, cast, beats, checks, the encounter).
* The **outcomes**: every check's result (success or failure, by how much) and the fight, as a numbered action log. These are final. Never contradict them.
* The bible, the dossiers with voice sheets, and the style guide (system prompt).

## Cue reference

Each scene is `{ "id": "s1", "cues": [...], "battle_narration": [...] }` with the plan's scene ids, in order. The assembler adds the title card, the DM intro, scene changes, location cards, music and the cast's starting positions, so start each scene with dialogue or action.

| op | fields | use |
| --- | --- | --- |
| `say` | `speaker` (actor id on stage), `text`, optional `emote` | dialogue. `emote`: neutral, happy, smile, sad, shock, sweat, dots, exclaim, alert, question, angry, love, heartbreak |
| `narrate` | `text` | the Storyteller. Third person, present tense |
| `move` | `actor`, `to: [x, y]`, optional `face`, `wait` (false = walk while the next line plays) | walking; the path is found for you |
| `face` | `actor`, `facing` (up/down/left/right) | turn to look |
| `emote` | `actor`, `emote`, optional `sfx` | a bubble without words |
| `spawn` / `despawn` | `actor`, `sprite`, `at`, `facing`, `name` | someone enters or leaves (spawn off the map edge and `move` in for an entrance) |
| `camera` | `to: [x, y]`, `duration` | pan |
| `lantern` | `id`, `state` (lit/flicker/dead), optional `unlight` | a lantern changes |
| `time_of_day` | `preset` (day/morning/dusk/evening/night), `duration` | light changes |
| `sfx` | `id` | one sound |
| `wait` | `seconds` | a beat of silence (use sparingly) |
| `check` | `id` (from the plan) | **the dice tray shows this roll here.** Put it at the moment the character tries, then react on the next line |
| `encounter` | `id` (from the plan) | **the fight plays here** from the engine's log |

Each plan check appears exactly once, in its scene. The encounter appears exactly once. Aftermath rolls (`a1`, `a2`: the engine's healing of anyone left dying after a won fight, see `10_rules_of_play.md` §5) are placed like checks, in the scene the outcomes name. Offscreen checks (`offscreen: true`) are not shown; mention their result in a line if it matters.

`battle_narration` puts Storyteller lines into the fight: `{ "after": N, "text": ... }` plays after action N of the action log (0 = right after initiative). Use 3-6 of them for the moments that matter (first blood, a character going down, a clever move, the last blow). They must agree with the log: who hit whom, who fell, who stood up.

## Writing rules (from `08_voice_and_style.md`, all binding)

* At most **140 characters per box**. Split longer thoughts into two boxes or two speakers.
* At most 2 boxes in a row from one speaker. Break speeches with action or another voice.
* The narrator never states a die number - the overlay already shows it. Describe the result.
* Each character sounds like their voice sheet. Nicknames, rhythm and "never says" rules are binding.
* Names over pronouns at the start of each scene.
* No modern slang, no fourth-wall jokes about dice or games, none of the banned clichés.
* A success should feel earned, a failure should cost something or open a door; never make a failure secretly a success.
* Foreshadow secrets only with a look, an object or a half-line. Never state them.
* The last box of the episode is a party member's line (the assembler then adds "Next time: ..." from `next_time`).
* After a fight everyone stays where it left them (`end_state.pos` in the outcomes); anyone at 0 HP lies there and cannot speak or walk until healed. A `continue` scene starts from those positions.
* Use only actors who are on stage (the scene's cast, plus anyone you `spawn`). The fight's enemies are spawned for you if they are not already on screen.

## This episode

Episode id: {{episode_id}}

### Plan
{{plan}}

### Outcomes (final)
{{outcomes}}

### State before the episode
{{state_view}}

### Story so far
{{recap}}
{{feedback}}
