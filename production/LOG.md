# Production log

## Summary: Campaign 1, Episodes 2-10 (shift-20261005-0648, finished 2026-10-05)

All 17 queue tasks are done; nothing is blocked.

Episodes (runtime):
- E2 The Goblin Who Talked (7.9 min): Rusk talks; Maddy's free board; velvet-thread hook.
- E3 The Empty Housing (6.1 min): Lantern 37's core was lifted out by hand; trail into Thornpike Woods.
- E4 Wolves at the Birches (6.7 min): Pell summoned for the first time; wolf fight, Tamsin downed and healed.
- E5 The Scout Camp (6.0 min): Tamsin's bluff; scout camp taken; three dead cores recovered.
- E6 First Watch (6.3 min): campfire bond episode; painted anvil, the key hums, Brannoc's lantern.
- E7 The Saint of the Open Hand (7.0 min): Tobin's two stories; Lantern 41 dies; Rook's letter.
- E8 Wending Mill (6.4 min): mill-yard fight; the barn is set alight.
- E9 Smoke Over the Millpond (7.2 min): goblin boss; Oriel drops and makes her death saves; Brannoc holds alone.
- E10 Fort Harrow (6.2 min): Ironvow name revealed; Rook hires the party; the black-glass pendant.

Maps: crooked_kettle_interior (optional, used in E7), thornpike_woods, wending_mill (+ wending_mill_burning), fort_harrow.
Materials: Pell (recoloured pack owl), camp props, dead-core and cart sprites, mill/barn composites, villagers,
soldiers, fort walls and gate, black-glass pendant. Stand-ins are listed in README "Materials still wanted".

Engine/tooling fixes: contest roll labels; lantern cue sfx flag; speaker sprite lookup for ids like goblin-1;
long rests clear 'prone'; the queue test no longer pins the live queue (it would have made the relay reject
every bundle that records progress).

Relay note: the Action applied nothing between 06:37 and at least 08:18 UTC, so bundles were held and
uploaded in order. Bundles 004-006 were moved to the Drive trash before the Action ran (they predate the
test fix in 008) and were re-uploaded after it.

## Entries

- 2026-10-04 19:27 UTC - Setup session: Episode 1 committed, Lantern Road map built, queue created.
- 2026-10-05 06:30 UTC - Relay test from the setup session: Drive bundle -> GitHub Action.
- 2026-10-05 07:00 UTC - Episode 2 'The Goblin Who Talked' produced (7.9 min, 3 checks: Oriel persuasion success, Ilsevel insight success, Tamsin deception vs Ilsevel insight failure). Contact sheet review: moved Tamsin's s2 mark off the inn lantern and walked Ilsevel up one square so the camera keeps Rusk clear of the dice tray. Fixed contest roll labels (opponent now shows their own skill) in pqc/pipeline/resolve.py.
- 2026-10-05 07:09 UTC - map:crooked_kettle_interior built (25x15): scripts/maps/crooked_kettle_interior.py, 30 new props in the manifest (one-tile wall pieces with door end-caps, interior furniture from TilesetElement, hearth/brazier/candle lights) and a floor_wood terrain. Points: front_door, common_room, hearth, hearth_east, bar, behind_bar, table_west, table_south, table_east, stairs, storeroom_door, storeroom, rusk_corner.
- 2026-10-05 07:19 UTC - Episode 3 'The Empty Housing' produced (6.1 min; Tamsin sleight of hand barely succeeded, Ilsevel investigation failed, Brannoc survival failed by a lot). Added an Unlight zone cue at dead Lantern 37 so the grey grass shows on screen; the assembler now passes a lantern cue's sfx flag through (sfx: false = no 'lantern out' sting for a lantern that is already dead).
- 2026-10-05 07:31 UTC - map:thornpike_woods and materials:woods done. Points: west_entry, trail_west, fork, clearing_south/center/west/east/north, camp_approach, camp_overlook, camp_west, camp_center, camp_fire_north, camp_cart, camp_tent, east_exit, hollow_entry, campsite, campsite_east, campsite_south, waymarker_side, watch_post. Stand-ins listed in README 'Materials still wanted'. Also fixed tests/test_pipeline.py: the queue test pinned the live queue to 'episode:2 is next' and would have made the relay reject every bundle that records progress; bundles 004-006 were pulled from the folder before the Action ran and are re-uploaded after the fix (008) is applied.
- 2026-10-05 07:36 UTC - Episode 4 'Wolves at the Birches' produced (6.7 min). Pell summoned for the first time. Ilsevel's owl-sight perception failed; wolves won initiative, a wolf crit dropped Tamsin, Oriel's Healing Word brought her back; party won in 3 rounds (150 XP). Ilsevel ends at 4/8 HP, Tamsin 7/10; no rest yet (E6 is the night camp).
- 2026-10-05 07:42 UTC - Episode 5 'The Scout Camp' produced (6.0 min): group stealth and Tamsin's bluff succeeded, camp taken in 2 rounds (100 XP); party holds 3 dead lantern-cores. Fixed the renderer: a speaker whose actor id differs from its sprite (goblin-1 -> goblin_warrior) now uses the sprite it was spawned with (pqc/render/timeline.py). Banned word 'menacing' caught by the mechanical check and rewritten.
- 2026-10-05 07:47 UTC - Episode 6 'First Watch' produced (6.3 min): bond episode at the hollow; painted-anvil and key-hum hooks planted, Brannoc gives Oriel his lantern; long rest to the morning of 5 Emberfall. Two checks (history, sleight of hand) both succeeded. Wiki facts: a hook id containing a spoiler word was refused by the spoiler check and removed from hooks_planted.
- 2026-10-05 07:52 UTC - Episode 7 'The Saint of the Open Hand' produced (7.0 min), first use of the inn interior map. History and Religion checks both failed (Oriel felt nothing from the dead core). Lantern 41 dead; Rook's letter opens q.wending-mill; long rest to 6 Emberfall. Note for writers: 'first light' is caught by the spoiler list, use 'dawn'.
- 2026-10-05 07:59 UTC - Maps wending_mill (+ wending_mill_burning) and fort_harrow built; materials for both added in one manifest pass. Points - mill: north_road, road_bend, yard_gate, mill_yard, yard_west/east/south, mill_door, millpond_bank, well_side, barn_front, barn_yard, barn_west, barn_south, cottage_north, cottage_east, east_exit, south_field. Fort: road_south, gate_outside, gate_inside, courtyard, command_door, before_command, parade_west, mess, barracks_door, training_yard, yard_east, well_side.
- 2026-10-05 08:04 UTC - Episode 8 'Wending Mill' produced (6.4 min): group athletics passed, mill-yard fight won in 3 rounds (175 XP), Brannoc used both Second Winds, Tamsin dropped to 2 HP and was healed. Ends on the burning barn (wending_mill_burning map). New NPC: Ned Hollis, the miller. Fixed a script race (despawn while a non-waiting move was running).
- 2026-10-05 08:09 UTC - Episode 9 'Smoke Over the Millpond' produced (7.2 min): Brannoc freed the barn doors, Oriel's medicine failed (out of position), the goblin boss dropped Oriel, who made her death saves (fail, success, success, stable); Brannoc held the boss alone down to 2 HP and Ilsevel's fire bolt killed it (275 XP). Brannoc stabilised Oriel (aftermath). Long rest to 7 Emberfall. Fixed villager_c (the OldWoman sheet has only two rows; now Villager3).
- 2026-10-05 08:18 UTC - Episode 10 'Fort Harrow' produced (6.2 min): Ironvow name revealed at the gate (shaft-nine hook planted), Rook hires the party at 10 gp/week each (gold added), Tamsin's haggle failed, Ilsevel's arcana shows the black-glass pendant drinks light. Act 1 complete. Long rests now also clear 'prone' (pqc/progression.py).
