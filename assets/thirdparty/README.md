# Third-party art

Curated from packs downloaded by hand and imported with `scripts/import_art.py` (the build machines can't
reach itch.io, OpenGameArt or kenney.nl). Credits and licences: `assets/CREDITS.md` and the licence file in
each folder.

| Folder | Pack | Licence | What's here | Manifest |
| --- | --- | --- | --- | --- |
| `kenney_roguelike/` | Kenney, Roguelike pack | CC0 | The whole sheet on a gap-free 16 px grid (57x31 tiles) | any `props` rect; add `"outline": true` |
| `dcss/` | Dungeon Crawl Stone Soup tiles | CC0 | `fire_tall` / `fire_small` (8-frame flame), `fire_ground`, `torch` strips; `items` and `creatures` sheets (32 px) | `fx`, `art.item`, `art.creature` |
| `painterly/` | Painterly Spell Icons, J. W. Bjerk | CC-BY 3.0 (attribution required) | One 64 px icon per SRD spell (`spell_icons.json` lists them) | `art.spell`, `Assets.spell_icon()` |

Kenney's art is flat; the outline pass gives it the Ninja Adventure look. DCSS art is 32 px and shaded:
its flames and torches work in the world, its items and creatures are for close-up cards and the wiki
(they don't have walk cycles). Painterly icons are painted: spell cards and the wiki, never in the world.
