---
id: recurring-npcs
title: Recurring NPCs
status: canon
---

# Recurring NPCs

Each entry: **id**, role, want, fear, voice, look (for sprites), first appearance, arc. Stat blocks reference SRD 5.2 creatures by id from `data/monsters.json` or are noted "build when needed". Party bonds with NPCs are tracked in `state/world.json` → `npc_relations`.

## Allies and friends

### Maddy Fenn — `npc.maddy-fenn`
- **Role:** innkeeper of the Crooked Kettle, Brindle Cross. Human, 50s.
- **Want:** her village safe and her inn full. **Fear:** the dark coming to her door; her son Wil joining the army.
- **Voice:** brisk, warm, rhetorical questions. "And who's going to pay for that, the Eight?"
- **Look:** round, flour-dusted apron, red headscarf.
- **Arc:** the home-base NPC. Her inn is the party's first "save point". If Brindle Cross falls in C8, her fate is a major emotional beat.

### Father Tobin Ashdown — `npc.tobin-ashdown`
- **Role:** priest of Aurelan, Oriel's adoptive father. Human, 64.
- **Want:** Oriel to be happy rather than holy. **Fear:** that his faith is a comfortable lie.
- **Voice:** soft, slow, gentle jokes, quotes scripture and then admits he doesn't understand it.
- **Look:** thin, white beard, faded gold stole, a cane.
- **Arc:** gives Oriel her first holy symbol (C1E1). In C8 he loses his sight to the Unlight and tells her the faith was always in people.

### Captain Edda Rook — `npc.edda-rook`
- **Role:** commander of Fort Harrow, Brannoc's former officer. Human, 40s. Stat block: SRD *Knight* (adapted).
- **Want:** enough soldiers to hold the road. **Fear:** failing her soldiers the way she believes the Crown has failed her.
- **Voice:** clipped, military, dry. "Report. Short version."
- **Look:** dented breastplate, short grey hair, scar through one eyebrow.
- **Arc:** the party's first employer. Becomes a general in C8.

### Pell — `npc.pell`
- **Role:** Ilsevel's owl familiar (Find Familiar). Spirit in owl form.
- **Voice:** does not speak; communicates in hoots that Ilsevel "translates" (comic device). Telepathic link means Ilsevel occasionally says, "Pell says you're an idiot."
- **Look:** small brown owl with one white feather.
- **Arc:** re-summoned whenever destroyed — a dramatic beat the first time (C1).

### Mother Fennick — `npc.mother-fennick`
- **Role:** archdruid of the Wardens of the Green. Gnome, ancient. Stat block: SRD *Druid* (adapted, higher level later).
- **Want:** the world to remember what came before the gods. **Fear:** being right.
- **Voice:** riddling, sing-song, speaks in nature metaphors and old rhymes. "The moth loves the lamp. Ask the moth how that ends."
- **Look:** tiny, moss-green cloak, staff taller than her, a beetle on her shoulder.
- **Arc:** cryptic hints from C1; reveals the old song of the First Light in C6.

### Aldous Venn — `npc.aldous-venn`
- **Role:** current High Lamplighter. Human, 60s.
- **Want:** to keep the order together. **Fear:** the archive's secret coming out — he knows part of it.
- **Voice:** tired, careful, bureaucratic, kind underneath.
- **Look:** grey coat with too many brass buttons, half-moon spectacles.
- **Arc:** ally who withholds the truth; confesses in C8.

### Hilde Ironvow — `npc.hilde-ironvow`
- **Role:** Brannoc's younger sister, presumed dead.
- **Arc:** see `05_history_timeline.md`. Appears as the aboleth's thrall in C6; freed; becomes the party's quartermaster and later Thane-in-exile.
- **Voice (free):** loud, laughing, braver than Brannoc. **Voice (thrall):** flat, perfect diction, speaks of herself as "this one".

### Corvina Lisle — `npc.corvina-lisle`
- **Role:** guildmistress of the Velvet Hand. Human, 50s. Stat block: SRD *Spy* / *Assassin* style (adapted).
- **Want:** what she is owed. **Fear:** losing face.
- **Voice:** velvet-polite threats, never raises her voice, calls Tamsin "little sparrow".
- **Arc:** antagonist in C3; reluctant ally in C8 when the Unlit threaten the cities.

### Wil Fenn — `npc.wil-fenn`
- **Role:** Maddy's teenage son (16), idolises Brannoc.
- **Arc:** joins the party as an NPC squire briefly in C1; later enlists. A recurring "the world is changing" barometer.

## Antagonists

### Ysolde Marr, the Quiet Flame — `npc.ysolde-marr`
- **Role:** former High Lamplighter, founder of the Unlit. Human, 79 but magically preserved, appears 50.
- **Want:** a world without gods or fate. **Fear:** that she is doing it for herself — to ascend — rather than for mortals.
- **Voice:** a teacher's voice: patient, precise, never cruel, uses the party's names. Asks questions more than she declares. "What would you do with a life no one had written for you?"
- **Look:** tall, iron-grey hair braided with brass wire, a Lamplighter coat dyed black, a lantern-pole with a black-glass housing that drinks light.
- **Stat progression:** never fought directly before C8. Build custom stat blocks from SRD *Archmage* in C8–C9, demigod form in C10.
- **Arc:** voice-only presence (letters, recordings in Lamplighter crystals) in C1–C3; appears in person at the end of C4; offers the party an alliance in C6; becomes the open enemy in C8; final confrontation in C10. Must remain sympathetic to the end.

### The Five Wicks (Ysolde's lieutenants)

| Id | Name | Species | Role | Campaigns | Fate (planned) |
| --- | --- | --- | --- | --- | --- |
| `npc.wick-cinder` | **Cinder** (Tobias Pryce) | Human | Ex-priest of Kesh, fire-obsessed; Oriel's dark mirror | C2, C3, C7 | Redeemable |
| `npc.wick-hush` | **Hush** | Tiefling | Assassin of few words; Tamsin's dark mirror | C3, C5, C8 | Dies or defects |
| `npc.wick-thorn` | **Thorn** (Ellarin Vey) | Elf | Ilsevel's former rival among the Wicks | C4, C6 | Rivalry → grudging respect |
| `npc.wick-anvil` | **Anvil** (Dorrek Stoneback) | Dwarf | Exiled clan engineer, dug Shaft Nine; Brannoc's dark mirror | C5, C6 | Dies in C6 |
| `npc.wick-ash` | **Ash** | Unknown (masked) | Ysolde's closest; revealed as Aldous Venn's son, **Corin Venn** | C1 (voice), C8, C9 | Revealed in C8 |

### Campaign bosses

| Campaign | Boss | SRD base | Want | Note |
| --- | --- | --- | --- | --- |
| C1 | **Skarrow the Lantern-Eater**, goblin warlord | Goblin Boss (scaled) | Power and coin for goblins long kept out of the light | Wears a crown of lantern glass. Can be negotiated with. |
| C2 | **Prior Edric Vane**, wight abbot | Wight | To finish the abbey's last rite and be allowed to die | Tragic; the Heartflame bound him. |
| C3 | **The Brine Sisters** (Grisel, Morwa, Salt-Annie) | Sea Hag ×3 (coven) | To trade drowned sailors' souls for divine flame | Comic and horrible. |
| C4 | **Lady Sorrelwyn**, Duchess of Dusk | Original fey noble built from SRD components | To make the Gloaming permanent where lanterns die | Not necessarily fought. |
| C5 | **Jarl Brakka Emberjaw**, fire giant chieftain | Fire Giant | To forge an Unlit-fuelled war engine | Honour duel possible. |
| C6 | **Ulathyx, the Drowned Thought** | Aboleth | To keep Hilde and the Archive's secrets | Psychic horror. |
| C7 | **Vizier Ombrasel** | Lich | To keep ruling forever | Phylactery hidden in the Gloamkey vault. |
| C8 | **Vorthaxis Stormcrown** | Adult Blue Dragon | To claim Highcrest's Beacon as hoard | Ysolde's ally. |
| C9 | **General Malcarrow** | Pit Fiend | To buy the Heartstone from whoever wins | Fiends as merchants. |
| C10 | **Ysolde, the Unlit Saint** (ascending) + **Caldrazzar the Last Gold** | Custom demigod; Ancient Gold Dragon | See arc | The dragon may be ally or foe. |

## Minor recurring

- **Brother Ambrose** (`npc.brother-ambrose`) — a nervous young Lamplighter Wick who keeps getting sent to dangerous places. Comic relief; survives against all odds.
- **"Saint" Petra Glim** (`npc.petra-glim`) — a travelling merchant with a mule called Prophecy; appears in every campaign as the shop.
- **Rusk** (`npc.rusk`) — a goblin who defects to the party in C1 if treated well; becomes a minor recurring ally.
