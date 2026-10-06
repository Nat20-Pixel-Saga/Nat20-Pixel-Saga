---
id: rules-of-play
title: Rules of Play
status: canon
---

# Rules of Play

The show uses the **System Reference Document 5.2 (SRD 5.2)**, released by Wizards of the Coast under CC-BY-4.0, as its rules base. This file states how the rules are applied on the show and which choices the engine makes. The code in `/pqc` implements it.

## 1. Division of labour

| Who | Decides |
| --- | --- |
| **Planner (Claude)** | What characters try to do, which checks are needed, and their DCs (within §3). |
| **Rules engine (code)** | Every die, every modifier, every outcome, HP, slots, conditions, XP, gold. |
| **Writer (Claude)** | How the outcome is described. Must match the engine's event log exactly. |
| **Showrunner (human)** | Approves campaign bibles, can veto a beat, may award Heroic Inspiration once per week as a "table moment". |

## 2. Dice

- All dice are rolled by `pqc.dice.Dice`, seeded per episode with `"<campaign>-<episode>-<attempt>"`, e.g. `C01-E001-1`.
- Each die is derived from HMAC-SHA256(seed, draw-counter) with rejection sampling, so any single roll can be re-verified from the seed and its counter. Seeds and full logs are published on the wiki.
- **Rerolling an episode is forbidden** once its plan has been resolved. If a technical failure requires a rerun, the attempt number increments and the reason is logged in `episodes/<id>/episode.json` (`attempt_reasons`).

## 3. Setting DCs

| Difficulty | DC |
| --- | --- |
| Very easy | 5 |
| Easy | 10 |
| Medium | 15 |
| Hard | 20 |
| Very hard | 25 |
| Nearly impossible | 30 |

- The planner must justify any DC ≥ 20 in the plan's `reason` field.
- Don't call for a roll when failure would be boring or success is certain; the plan marks those `auto: success`.
- **Passive scores** (10 + modifiers) are used for noticing things nobody is actively searching for.
- **Group checks:** the group succeeds if at least half succeed.
- **Help:** a helper grants advantage on the next check or attack (SRD Help action).

## 4. Combat conventions

- **Grid:** 5-ft squares; diagonals cost 5 ft. Positions are integer coordinates in `encounter.combatants[].pos`.
- **Initiative:** d20 + Dex modifier (+ bonuses such as Alert); ties broken by higher Dex, then a seeded roll-off.
- **Critical hits:** natural 20 (or the attacker's expanded range, e.g. Champion 19–20); double the damage dice, not modifiers.
- **Natural 1** on an attack always misses. Natural 1/20 have no special effect on checks or saves except Death Saves.
- **Opportunity attacks** are automatic for creatures with a reaction when an enemy leaves their reach without Disengage. Moving *into* reach never provokes. Sneak Attack and Savage Attacker can apply to them ("once per turn", which includes other creatures' turns; from C1E11).
- **Surprise:** a creature caught unready (the night watch failed its check, an ambush the party didn't spot) rolls Initiative with disadvantage (SRD 5.2). The plan says who: `"surprise": {"party": "c3.failure", "enemies": "c3.success"}`.
- **Monster tactics** (the engine's policy, from C1E11): goblins use Nimble Escape, slipping past a well-armoured defender to reach a softer target and, once hurt, hitting and Disengaging out of reach to shoot; shooters step in to normal range rather than throw or shoot with disadvantage.
- **Reactions** used automatically by the engine when the outcome is unambiguous: *Shield* (only if +5 AC turns a hit into a miss), opportunity attacks. Other reactions require an explicit intent.
- **Monsters at 0 HP** die unless the plan marks them `nonlethal` (knock-out). **Party members at 0 HP** fall unconscious and make Death Saving Throws.
- **Flanking** is not used (optional rule, off).
- **Cover:** half (+2) and three-quarters (+5) are applied when the plan's map marks it; total cover blocks targeting.
- **Weapon Mastery:** Vex, Sap, Slow, Graze, Topple and Push are automated. Cleave and Nick are resolved as explicit extra-attack intents when added (Phase 2).

## 5. Rest, recovery and resources

- **Short rest:** 1 hour; anyone below half HP spends Hit Point Dice until back to half (rolled in the episode's dice log, from C1E11); class features recover as SRD 5.2.
- **Long rest:** 8 hours; regain all HP, all Hit Point Dice, all spell slots; reduce Exhaustion by 1. It needs at least 1 HP. A night attack is staged as a fight in the night scene, with the rest proposal after it.
- **Camps** (from C1E11): a night in the open is a long rest with a camp (`site`, `watches`, `lantern_lit`). Everyone eats a ration (their own, then the shared packs, then a friend's); anyone without one goes hungry, which the writer shows. The watch order goes to the writer: who sits up with whom is where bonds grow. The Unlight rule (§6) applies at the camp.
- **Travel** (from C1E11): `{"type": "travel", "days": N, "to": "<location>"}` moves the clock N days, costs a ration a day each and ends with the party rested. At least one of those nights gets a scene.
- **Heroic Inspiration:** humans gain it from each long rest (Resourceful). The showrunner may award it once per week. A creature with Heroic Inspiration may reroll one die and must use the new roll.
- **Encumbrance:** tracked only for absurd cases; carrying capacity is Str × 15 lb.
- **Ammunition:** tracked; half is recovered after a fight.
- **Money:** tracked exactly in copper in `state/party/*.json`.
- **After the fight:** when the party wins, nobody is left dying. Each downed, living party member is brought back by the best means at hand, in this order: a healing spell from a conscious caster with a slot left (the slot is spent and the healing rolled on screen), the *Spare the Dying* cantrip (stable, wakes with 1 HP after 1d4 hours), or a DC 10 Wisdom (Medicine) check by the best medic. The engine does this (`pqc.pipeline.resolve.triage`); the writer places the roll as `{op: "check", id: "a1"}` in the next scene.

## 6. The Unlight (original rules)

| Zone | Effect |
| --- | --- |
| **Fringe Unlight** | Colour drains (visual only). Animals refuse to enter. |
| **Deep Unlight** | A creature that finishes a long rest here gains 1 Exhaustion level unless it succeeds on a DC 12 Wisdom save. Lantern light (any lit lantern within 60 ft) prevents this. |
| **Abyssal Unlight** (Underdeep depths, C6+) | As deep; plus at the start of each hour, DC 15 Wisdom save or forget one minor memory (narrative, recorded on the wiki). |

From C1E11 the engine rolls these saves at every camp rest in deep or abyssal Unlight with no lantern lit at the camp; they go in the public dice log.

Undead and fiends are uneasy inside a lantern ward: they have disadvantage on Charisma checks there (narrative tell). Hollowed and gloams use SRD undead stat blocks re-skinned (see `06_recurring_npcs.md`).

## 7. Levelling

- **XP with milestones** (from C1E11). Encounter XP (SRD stat blocks, shared equally) and story XP build towards the next level on the SRD table; a character levels up at the end of the episode in which they reach it. The milestone episodes in `07_campaign_arcs.md` (`milestone_level` in the campaign file) top everyone's XP up to that level's threshold, so the planned beats always land. Before C1E11 levels were by milestone only and XP was flavour.
- **What a level brings** is applied from the dossiers' level plans (`data/level_plans.json`): subclass, expertise, spells added to the book or prepared, ability increases. Anything the plan doesn't cover (or a spell the engine doesn't have yet) is reported as still to choose.
- **On screen:** the end card before the outro shows each character's level, XP and XP to the next level, whenever anyone gained XP or a level and at least every third episode; a level-up gets its own beat in the last scene (`prompts/writer.md`).
- **Hit points on level-up:** fixed average (SRD option). This keeps the show fair and predictable.
- **Ability Score Improvements / feats** at levels 4, 8, 12, 16, 19 follow the plan in each dossier unless the story suggests otherwise; any change requires a dossier update.
- **Multiclassing:** not used.

## 8. The SRD boundary

- Allowed: SRD 5.2 classes and their SRD subclasses (Champion, Evoker, Thief, Life Domain for the party), SRD species, backgrounds, feats, spells, equipment, magic items and monsters.
- Not allowed: non-SRD subclasses, spells, monsters, named characters, gods or settings from any published D&D product. Invent originals instead and build them from SRD parts.
- Monster stat blocks used on screen must be checked against the SRD 5.2 text before the episode is published. The engine's `data/monsters.json` notes which entries have been verified (`"verified": true`).
- Required attribution (every video description and the wiki footer): *"This work includes material from the System Reference Document 5.2 ("SRD 5.2") by Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2 is licensed under the Creative Commons Attribution 4.0 International License, available at https://creativecommons.org/licenses/by/4.0/legalcode."* (Check this wording against the official SRD 5.2 page before launch.)
- The show describes itself as "compatible with fifth edition" and never uses the Dungeons & Dragons logo or trade dress.

## 9. House rules (deliberately small)

1. **Potion as a bonus action:** drinking a potion yourself is a Bonus Action; administering it to another creature is an action.
2. **Narrative death protection:** none. But a PC who dies may be raised by an NPC temple for the SRD price if the party can pay — the debt is tracked.
3. **Dramatic pause:** the showrunner may stop an episode before a roll that could kill a PC and end on the cliffhanger; the roll is then resolved first thing in the next episode.
