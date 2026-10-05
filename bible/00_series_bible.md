---
id: series-bible
title: Nat 20 Pixels — Series Bible
version: 1.0
status: canon
---

# Nat 20 Pixels — Series Bible

This is the master reference for every model and every human who writes, plans, draws or checks an episode. When anything in a script, plan or wiki page disagrees with this bible, the bible wins unless the bible itself has been amended by a logged retcon (see §12).

The bible is split into files so that prompts can include only what they need:

| File | Contents | Include in prompts |
| --- | --- | --- |
| `00_series_bible.md` | The show, tone, rules of the table, the overarching arc, writing rules | Always (cached) |
| `01_world_and_cosmology.md` | The world of Talmerra, magic, the Lanterns, the Dimming, calendar | Always (cached) |
| `02_pantheon.md` | The Eight, worship, divine magic | When gods, clerics or temples appear |
| `03_gazetteer.md` | Regions, cities, routes and dungeons for all ten campaigns | The current region + neighbours |
| `04_factions.md` | Organisations, their goals, leaders and attitudes to the party | Factions tagged in the beat |
| `05_history_timeline.md` | Ages, key dates, secret history | Planning calls only |
| `06_recurring_npcs.md` | Allies, rivals, villains that span campaigns | NPCs tagged in the beat |
| `07_campaign_arcs.md` | Ten campaigns + interludes, beats, bosses, reveals | Planning calls; current campaign only for daily calls |
| `08_voice_and_style.md` | Narrator voice, dialogue rules, banned clichés, voice sheets index | Always (cached) |
| `09_visual_audio_style.md` | Palette, sprite rules, UI, spell-effect grammar, music cues | Asset and render calls |
| `10_rules_of_play.md` | How dice, rules and adjudication work on the show | Always (cached) |

---

## 1. The show in one paragraph

*Nat 20 Pixels* follows four unlikely companions — a disgraced dwarf soldier, an elf archivist, a halfling pickpocket and a foundling priestess — from their first night on a failing frontier road to the moment, two years later, when they decide whether the gods of their world deserve to keep burning. It is an actual-play adventure told as a 16-bit top-down RPG: every swing, spell and lie is decided by real dice, and the story bends around the results.

## 2. Premise and central question

**Premise.** Across the world of Talmerra, lanterns lit by an ancient order hold back the Unlight — a cold dark that is not shadow but absence. The lanterns burn with *divine flame*, a fire the gods give in exchange for mortal prayer. For a thousand years that bargain held. Now the lanterns are going out, one road at a time. People call it the Dimming.

**Central question of the series.** *Is a light worth keeping if it costs you your freedom?* The gods protect mortals, but they also feed on their devotion and quietly steer their fates. The series' antagonist believes mortals should be free of both. The party must find out whether she is a monster, a prophet, or both — and what they will put in the gods' place.

**Emotional promise.** Found family. Four people who start as strangers and end as a household. Every campaign must deepen at least one bond and test at least one.

## 3. Tone

- **Warm, adventurous, occasionally funny, sometimes devastating.** Think of a well-run home campaign with good friends: banter at camp, real stakes in the dungeon.
- **Earnest over ironic.** Characters can joke, but the show never sneers at its own story.
- **Hope is the default; darkness is earned.** Tier 1 (levels 1–4) is local and light. The tone darkens through tiers 2–3 and becomes mythic in tier 4.
- **Consequences are real.** Villages that are not saved stay burned. NPCs who die stay dead unless the party pays for a resurrection on screen.
- **Rating:** suitable for a general audience aged 12+. Violence is pixel-art stylised: no gore, no torture on screen, no sexual content. Romance is allowed and stays at the level of glances, confessions, hand-holding and a fade-to-black kiss.

## 4. The party

| Id | Name | Species / class (SRD subclass at L3) | Background | Deity | One-line |
| --- | --- | --- | --- | --- | --- |
| `brannoc` | Brannoc Ironvow | Dwarf Fighter (Champion) | Soldier | Vigrun the Anvil | An exile who thinks he deserves the worst and keeps getting between his friends and it. |
| `ilsevel` | Ilsevel Starwick | Elf (High Elf lineage) Wizard (Evoker) | Sage | none (scholar of all) | A brilliant archivist who trusts books more than people — especially her missing mentor. |
| `tamsin` | Tamsin Underbough | Halfling Rogue (Thief) | Criminal | Quill the Laughing Thief | A charming liar running from a debt and toward the only people who never asked her to pay it. |
| `oriel` | Oriel Ashdown | Human Cleric (Life Domain) | Acolyte | Aurelan the Lantern-Bearer | A foundling priestess whose faith in the light is the first thing the Dimming comes for. |

Full dossiers live in `/dossiers/`. Mechanical truth lives in `/state/party/*.json` and is owned by the rules engine.

## 5. The overarching arc in five sentences

1. The Lantern Road's lights are being snuffed by goblins under a warlord who has learned that darkness pays — someone is buying the dead lantern-cores (Campaign 1).
2. The buyer is the Unlit, a secret society serving **Ysolde Marr**, once High Lamplighter and Ilsevel's mentor, who is harvesting divine flame from lanterns, saints' relics and holy sites across Talmerra (Campaigns 2–7).
3. Ysolde has learned the truth hidden in the Lamplighter archives: the Eight gods are not creators but survivors who devoured a ninth, the First Light, and who sustain themselves on mortal prayer — and the Unlight is the First Light's dying, not an enemy (Campaigns 6–8).
4. She means to gather enough flame to ascend, unmake the Eight and give mortals a world with no gods and no fate — at the cost of the lanterns' protection, which would leave millions in the dark while her new order takes hold (Campaigns 8–9).
5. At level 20 the party must choose: restore the Eight, let Ysolde's world be born, or forge a third path in which the First Light is rekindled and shared by mortals themselves (Campaign 10). The planned ending is the third path, but the dice and the party's choices can change it, and the plan must be rewritten if they do.

## 6. Pillars of an episode

Every episode serves at least two of these four pillars; every week serves all four.

1. **Explore** — new screens, secrets, a map that fills in.
2. **Fight** — tactical, readable combat with dice on screen.
3. **Talk** — NPCs with wants, negotiation, deception, comedy.
4. **Bond** — the party learning, hurting, helping each other.

## 7. Structure and cadence

- One episode per weekday, 5–10 minutes, ~800–1,200 words of on-screen text.
- Campaigns of ~40–45 episodes (≈2 months), two character levels per campaign, ten campaigns.
- Interludes of ~5 episodes between campaigns: downtime, shopping, training, bonding, a character's personal side quest.
- Roughly one level per real month. Levels are awarded by **milestone** at campaign beats listed in `07_campaign_arcs.md`; XP is still tracked for flavour on the wiki.
- **Week rhythm (guideline):** Mon — new location or hook; Tue/Wed — exploration and talk; Thu — escalation, usually a fight; Fri — cliffhanger or a quiet campfire bond scene.

## 8. Series-wide rules for writers

1. **Dice are sovereign.** The writer proposes intents; the engine rolls; the writer narrates the result truthfully. Never describe a hit that the log records as a miss. Never invent damage, HP or slots.
2. **No retroactive edits to rolls.** If a roll ruins the plan, the plan changes, not the roll.
3. **Show the dice that matter.** Every attack, save, check with a DC, death save and initiative roll appears on screen. Trivial checks the plan marks `offscreen: true` may be summarised.
4. **Every NPC wants something.** A named NPC has a want, a fear and a way of talking, recorded on their wiki page at first appearance.
5. **The party drives.** At least one meaningful choice per episode comes from a party member's personality, not from the plot.
6. **Four voices, always distinct.** Use the voice sheets. If a line could be said by any of them, rewrite it.
7. **Pay off what you plant.** Every Chekhov item, prophecy line or hook gets a wiki entry tagged `open-hook`, and the weekly audit lists unresolved ones.
8. **Respect the SRD boundary.** Use only SRD 5.2 rules content, plus original creations. Never use non-SRD named creatures, settings, characters or spells (see `10_rules_of_play.md` §8).
9. **No real-world references,** brands, memes or anachronistic slang.
10. **The narrator never lies.** The narrator may withhold, but what the narrator states as fact is true in the world.

## 9. What the show is not

- Not grimdark. No cruelty for its own sake, no sexual violence, no torture scenes.
- Not a parody of D&D or of video games. It borrows the comfort of both and plays it straight.
- Not a power fantasy. The party loses fights, fails rolls, runs away, and must sometimes accept a worse outcome.
- Not a lore dump. Lore arrives through places, objects and people, a few lines at a time.

## 10. Content guardrails

- Death of party members is possible. If a party member dies, the next episode is a funeral or a resurrection quest; a replacement character is introduced only with the showrunner's approval.
- Children are never harmed on screen.
- Real-world religions are never referenced; the Eight are wholly fictional.
- Villains may be sympathetic; their atrocities are reported, not lingered on.

## 11. Glossary

| Term | Meaning |
| --- | --- |
| **Talmerra** | The world. |
| **The Eight** | The gods of Talmerra (see `02_pantheon.md`). |
| **First Light** | The ninth, oldest power, devoured by the Eight in the Age of Kindling; its embers are the source of all divine flame. Secret until Campaign 6. |
| **Divine flame** | The holy fire that burns in lanterns, altars and relics; it is the gods' gift and their food. |
| **Lantern** | An iron-and-glass post that burns divine flame and keeps the Unlight away. A **lantern-core** is the crystal at its heart. |
| **Lamplighters** | The ancient order that builds and tends the lanterns. |
| **The Dimming** | The present crisis: lanterns failing across the world. |
| **Unlight** | The cold, colourless dark beyond the lanterns' reach; it drains warmth, memory and colour. Mechanically, see `10_rules_of_play.md` §6. |
| **The Unlit** | Ysolde Marr's secret society. Members wear black-glass pendants. |
| **Gloaming** | The fey realm that touches Talmerra at dusk. |
| **Underdeep** | The vast caverns beneath Talmerra. |
| **The Sundered Planes** | The shattered realms formed from the First Light's corpse. |

## 12. Canon management

- **Canon tiers:** (1) this bible; (2) `state/` JSON; (3) the wiki; (4) the episode scripts. Higher tiers override lower ones.
- **Retcons** are allowed only through a pull request that edits the bible or the wiki and adds an entry to `bible/RETCONS.md` with the reason and the episodes affected.
- **Canon digest:** each month, the wiki is summarised into `wiki/canon-digest.md` (≤15k tokens). Daily prompts include the digest, not the whole wiki.
- **Spoilers:** secret facts are written in this bible inside blocks marked `> SECRET (reveal: C#E#)`. Wiki pages must never include a secret before its reveal episode.
