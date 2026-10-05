---
id: gazetteer
title: Gazetteer of the Vael
status: canon
---

# Gazetteer of the Vael

Locations are listed by region, in the order the party first reaches them. Every location has a stable `id` used in state, wiki front-matter and map files. Biome codes match the tilesets in `09_visual_audio_style.md`.

## Map overview

```
                 [Iron Peaks / Hold Aldhammer]          (north)
                         |
  [Thornwild / Gloaming] - [Corvane Heartland, Highcrest] - [Mirefen]
                         |
              [Lanternmarch / Lantern Road]
                         |
                   [Ember Coast]  ~~~ sea ~~~  [Saffron Empire / Sundered Desert] (south-east)
          (beneath everything: the Underdeep; above everything: the Sundered Planes)
```

---

## 1. The Lanternmarch (Campaign 1) — biome `meadow`, `forest`, `village`

A frontier march at the southern edge of the Kingdom of Corvane: rolling hills, birch woods, sheep, and the **Lantern Road**, the oldest lantern road in the Vael, running north–south for 140 miles.

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.brindle-cross` | Brindle Cross | Village (pop. 300) | **Series start.** A crossroads village around a market lantern. The *Crooked Kettle* inn. The shrine where Oriel grew up. |
| `loc.crooked-kettle` | The Crooked Kettle | Inn | Run by **Maddy Fenn**. The party meets here in C1E1. |
| `loc.shrine-of-the-open-hand` | Shrine of the Open Hand | Shrine to Aurelan | Run by **Father Tobin Ashdown**, Oriel's adoptive father. |
| `loc.lantern-road` | The Lantern Road | Road | 140 lanterns between Brindle Cross and Fort Harrow. Lanterns are numbered; the first to fail is **No. 37**. |
| `loc.fort-harrow` | Fort Harrow | Royal fort | A tired garrison of 40 under **Captain Edda Rook**. |
| `loc.wending-mill` | Wending Mill | Hamlet | Overrun by goblins in C1E8 unless the party arrives in time. |
| `loc.thornpike-woods` | Thornpike Woods | Forest | Goblin territory, wolves, an old druid circle. |
| `loc.goblin-warren` | Gnash Hollow | Cave complex | Skarrow's warren: three levels, a lantern-core hoard, a crude throne of lantern posts. |
| `loc.lamplighter-waystation` | Waystation Nine | Ruin | A Lamplighter maintenance house, abandoned 30 years ago; Ilsevel's first clue to Ysolde. |

## 2. Mirefen (Campaign 2) — biome `swamp`, `ruin`, `crypt`

A drowned lowland east of the Heartland: reeds, peat, will-o'-wisps, stilt-villages.

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.stilthollow` | Stilthollow | Stilt village | Fishers and reed-cutters; friendly but superstitious. |
| `loc.abbey-of-saint-halloran` | The Sunken Abbey of Saint Halloran | Dungeon | A great abbey that sank into the fen a century ago. Its relic, the **Heartflame of Halloran**, is a saint's divine flame. |
| `loc.bell-tower-isle` | Bell Tower Isle | Ruin | The only part of the abbey above water; its bell rings by itself. |
| `loc.marrowmere` | Marrowmere | Lake | Bog bodies; the hollowed walk here at night. |

## 3. The Ember Coast (Campaign 3) — biome `beach`, `volcanic`, `port`, `ship`

A hot, volcanic southern coast of black-sand beaches and pepper farms, ruled in name by Corvane and in fact by its merchant guilds.

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.port-sable` | Port Sable | City (pop. 20,000) | Smugglers' port. Home of the **Velvet Hand** thieves' guild, which Tamsin owes. |
| `loc.the-tarry-lantern` | The Tarry Lantern | Tavern | Neutral ground for guilds. |
| `loc.cinder-isles` | The Cinder Isles | Islands | Volcanic islands with pirate coves. |
| `loc.brine-sisters-grotto` | Saltgrave Grotto | Sea cave | Lair of the Brine Sisters, a coven of sea hags. |
| `loc.lighthouse-of-ondrel` | Ondrel's Lighthouse | Temple-lighthouse | The coast's great Beacon — targeted by the Unlit. |

## 4. The Thornwild and the Gloaming (Campaign 4) — biome `deep-forest`, `fey`, `court`

An ancient forest west of the Heartland. At dusk, its oldest groves open into **the Gloaming**.

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.hollowmere` | Hollowmere | Elven town | Ilsevel's birthplace: tree-houses around a mirror lake. Her family lives here. |
| `loc.grove-of-first-dusk` | Grove of First Dusk | Portal | The gateway to the Gloaming. |
| `loc.gloaming-court` | The Court of Thorns | Fey palace | A palace of living briar ruled by **Lady Sorrelwyn**, Duchess of Dusk. |
| `loc.mirror-maze` | The Mirror Maze | Dungeon | Where reflections bargain for names. |

## 5. The Iron Peaks (Campaign 5) — biome `mountain`, `snow`, `dwarf-hold`, `forge`

A northern mountain range. Dwarven holds along the passes; giants above the snowline.

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.hold-aldhammer` | Hold Aldhammer | Dwarven city | Brannoc's home, which exiled him. Ruled by **Thane Gerda Aldhammer**. |
| `loc.deepforge` | The Deepforge | Forge-temple | Vigrun's great temple; its Beacon is a forge-fire. |
| `loc.collapse-of-shaft-nine` | Shaft Nine | Mine ruin | The cave-in where Brannoc's sister Hilde was lost (C5 reveals she was taken, not killed). |
| `loc.mount-skarn` | Mount Skarn | Volcano | Fire giant stronghold of **Jarl Brakka Emberjaw**. |
| `loc.frostgate-pass` | Frostgate Pass | Pass | Avalanche set piece. |

## 6. The Underdeep (Campaign 6) — biome `cave`, `fungal`, `crystal`, `drowned`

Endless caverns beneath the Vael, lightless except for fungus and crystal. Deep Unlight pools in the lowest halls.

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.lowmarket` | Lowmarket | Neutral town | Stone-gnome and grey-dwarf traders (original peoples; use SRD gnome and dwarf mechanics). |
| `loc.fungal-cathedral` | The Fungal Cathedral | Wilderness | Glowing mushroom forest; home of the sporefolk, a gentle original fungal people (use SRD commoner-style stat blocks). |
| `loc.bleaching-hall` | The Bleaching Hall | Ruin | Where the Unlight is thickest; site of the first reveal about the First Light. |
| `loc.archive-beneath` | The Archive Beneath | Lamplighter vault | The Lamplighters' sealed archive. Ysolde found the truth here. |
| `loc.ulathyx-lake` | The Still Lake | Lair | Lair of the aboleth **Ulathyx, the Drowned Thought**, who holds Hilde. |

## 7. The Saffron Empire and the Sundered Desert (Campaign 7) — biome `desert`, `oasis`, `palace`, `tomb`

A wealthy theocratic empire across the Saffron Sea, devoted to Kesh. Beyond its river valley lies the **Sundered Desert**, glassed by an ancient fall of the First Light's fragments.

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.zahrun` | Zahrun, City of Domes | Capital | Seat of the **Ember Sultana Iskarah III**. |
| `loc.palace-of-ten-thousand-lamps` | Palace of Ten Thousand Lamps | Palace | Where the Vizier rules in the Sultana's name. |
| `loc.glass-wastes` | The Glass Wastes | Desert | Shards of fallen First Light; genies drawn to them. |
| `loc.tomb-of-the-first-sultan` | Tomb of the First Sultan | Dungeon | Where Vizier **Ombrasel** keeps his phylactery. |
| `loc.oasis-of-whispers` | Oasis of Whispers | Oasis | A djinni's court. |

## 8. Corvane Heartland and Highcrest (Campaign 8) — biome `city`, `castle`, `farmland`, `storm`

The kingdom's rich centre: wheat plains, river barges, and the capital.

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.highcrest` | Highcrest | Capital (pop. 120,000) | Walled city on three hills. The **Great Beacon** burns in the Cathedral of the Eight. |
| `loc.cathedral-of-the-eight` | Cathedral of the Eight | Temple | Seat of the Conclave. |
| `loc.lamplighter-hall` | Lamplighters' Hall | Guildhall | Order headquarters; Ilsevel trained here. |
| `loc.thunderhead-spire` | Thunderhead Spire | Lair | Lair of **Vorthaxis Stormcrown**, adult blue dragon, on a storm-wrapped crag. |
| `loc.kingsroad` | The Kingsroad | Road | Main artery; refugees flee the dark along it in C8. |

## 9. The Sundered Planes (Campaign 9) — biome `astral`, `bone-light`, `infernal`

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.ashen-fields` | The Ashen Fields | Realm of the dead | Morrow's realm; the party meets lost NPCs. |
| `loc.ribcage-cathedral` | The Ribcage Cathedral | Fragment | A cathedral built in the First Light's ribs. |
| `loc.lower-furnace` | The Lower Furnace | Fiendish realm | Fiends trade in divine flame; **General Malcarrow**, a pit fiend, marshals an army. |
| `loc.heartstone` | The Heartstone | Fragment | The last ember of the First Light. |

## 10. The Hearth of the Eight (Campaign 10) — biome `divine`

| Id | Name | Type | Notes |
| --- | --- | --- | --- |
| `loc.hearth-of-the-eight` | The Hearth of the Eight | Divine realm | The gods' shared hall around an enormous, failing fire. |
| `loc.last-lantern` | The Last Lantern | Site | The original lantern, built in the Age of Kindling, at the edge of the world. |
