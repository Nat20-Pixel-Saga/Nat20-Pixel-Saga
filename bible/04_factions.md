---
id: factions
title: Factions
status: canon
---

# Factions

Each faction has a **reputation** track with the party in `state/world.json` (`factions.<id>.reputation`, −3 hostile to +3 devoted, starting values below). Beats may change it by at most ±1 per episode unless the plan marks a major event.

| Id | Faction | Leader | Goal | Start rep | First seen |
| --- | --- | --- | --- | --- | --- |
| `fac.lamplighters` | The Order of Lamplighters | High Lamplighter **Aldous Venn** (since Ysolde vanished) | Keep the lanterns burning; secretly, protect the archive's secret | 0 | C1E1 |
| `fac.unlit` | The Unlit | **Ysolde Marr** | Harvest divine flame, unmake the Eight, free mortals from fate | 0 (unknown) | C1 (unnamed) |
| `fac.conclave` | Conclave of Hierarchs | Hierarch-Primus **Benedikt Sorrow** | Preserve the church and the gods' worship | 0 | C2 |
| `fac.crown-of-corvane` | The Crown of Corvane | **Queen Maelis II** | Hold a frightened kingdom together | 0 | C1 (Captain Rook) |
| `fac.velvet-hand` | The Velvet Hand | Guildmistress **Corvina Lisle** | Profit; recover what Tamsin stole | −1 | C1 (letters), C3 |
| `fac.clan-aldhammer` | Clan Aldhammer | **Thane Gerda Aldhammer** | Survive the giants; protect clan honour | −1 (Brannoc is exiled) | C5 |
| `fac.gloaming-court` | The Court of Thorns | **Lady Sorrelwyn**, Duchess of Dusk | Expand the Gloaming as the lanterns fail | 0 | C4 |
| `fac.saffron-throne` | The Saffron Throne | **Ember Sultana Iskarah III** (puppet); Vizier **Ombrasel** (real power) | Make Kesh supreme; buy flame from the Unlit | 0 | C7 |
| `fac.wardens-of-the-green` | Wardens of the Green | Archdruid **Mother Fennick** | Balance; distrust of the lanterns | 0 | C1 (Thornpike circle) |
| `fac.sable-free-captains` | The Free Captains of Sable | Admiral **"Red" Jory Calloway** | Freedom of the seas, plunder | 0 | C3 |

## Faction notes

### The Order of Lamplighters

- **Ranks:** Wick (apprentice) → Lamplighter → Keeper → Master Keeper → High Lamplighter.
- **Look:** long grey coats with brass buttons, a lantern-pole that doubles as a staff. Pixel colour: slate grey with a brass highlight.
- **Culture:** practical, bookish, quietly heroic. Motto: *"One more mile of light."*
- **Secret:** the Master Keepers have always known lantern-cores are mined from First Light embers in the Underdeep; they do not know what the embers are. Only the High Lamplighter knew the full truth — which is how Ysolde learned it.

### The Unlit

- **Structure:** cells of three to seven, each led by a **Shade**. Cells don't know each other. Ysolde's lieutenants are the **Five Wicks** (see `06_recurring_npcs.md`).
- **Identification:** a black-glass pendant shaped like a snuffed candle. Members' eyes reflect no light when they lie.
- **Methods:** buy dead lantern-cores, steal relics, persuade disillusioned priests, hire monsters (goblins in C1, pirates in C3, giants in C5).
- **Ideology:** "No god's leash." Many members are sympathetic: people who lost loved ones to "the gods' will."

### The Conclave of Hierarchs

- Eight hierarchs, one per god. The Hierarch of Thessin never speaks.
- The Conclave suspects the gods are weakening and hides it to prevent panic. From C8 it becomes an obstacle: it would rather sacrifice the outer roads than admit the truth.

### The Velvet Hand

- A thieves' guild in Port Sable with branches in every city. Members wear a velvet thread at the wrist.
- Tamsin stole the **Gloamkey** (see dossier) from a Hand vault five years ago. The Hand wants it back, or the equivalent of 2,000 gp.

### Clan Aldhammer

- Dwarven clan of Hold Aldhammer. Honour is ledger-based: every oath is written in the **Book of Debts**.
- Brannoc's name is struck from the Book until he repays the "debt of Shaft Nine".

### The Court of Thorns

- Fey nobility; courtiers wear living flower crowns. Bargains are binding and literal.
- Lady Sorrelwyn courts Ysolde as an ally; she becomes neutral or hostile depending on C4 choices.

### The Saffron Throne

- Theocracy of Kesh with a magnificent bureaucracy. Arcane magic requires a licence stamped in red wax.
- Vizier Ombrasel is a lich who has ruled through six sultanas.

### Wardens of the Green

- Druids who have always distrusted the lanterns ("light that fears the dark is not light"). Mother Fennick knows the old songs about the First Light and gives cryptic clues from C1 onwards.

### The Free Captains of Sable

- A loose pirate federation. Can be allies in C3 and a fleet in C8.
