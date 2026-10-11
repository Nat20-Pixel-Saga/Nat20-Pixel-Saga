# The Pit

Arena fights on @Nat20px, decided by the same rules engine and seeded dice as the story: SRD 5.2.1 stat
blocks, every roll logged, a live win chance computed from the exact state of the fight. Season 1, **The
Bronze Crown**, is ten episodes on Wednesdays and Saturdays at 18:00 (Paris time), 21 October to 21
November 2026, plus a bonus that unlocks at 100 subscribers.

## Season 1

| # | Premiere | Format | Fight | Stakes |
|---|---|---|---|---|
| 1 | Wed 21 Oct | Duel, best of 5 | Lion vs Brown Bear | Crown place 1 |
| 2 | Sat 24 Oct | How many? | Goblins vs a Knight (4, 6, 8, 10, 12) | Special |
| 3 | Wed 28 Oct | Duel, best of 5 | Ghoul vs Goblin Boss | Crown place 2 |
| 4 | Sat 31 Oct | Rumble (8) | Halloween: 3 skeletons, 3 zombies, 2 ghouls | Special |
| 5 | Wed 4 Nov | Duel, best of 5 | Giant Spider vs Giant Hyena | Crown place 3 |
| 6 | Sat 7 Nov | How many? | Wolves vs an Allosaurus (2-6) | Special |
| 7 | Wed 11 Nov | Duel, best of 5 | Polar Bear vs Bandit Captain | Heavyweight special |
| 8 | Sat 14 Nov | Rumble (5) | Last Chance: the three losers + Dire Wolf + Ape | Wildcard place |
| 9 | Wed 18 Nov | Two duels, best of 5 | Bronze Crown semifinals | |
| 10 | Sat 21 Nov | Duel, best of 7 | Bronze Crown final | Season champion |
| Bonus | at 100 subscribers | How many? | Goblins vs a T-Rex (6-14) | Thank-you episode |

The fighters were chosen with simulations so each duel is a real contest (every CR 1 pairing was run
200-400 times; see `scripts/arena_season.py` and `pqc/arena/formats.py`). **Every seed is written in
`s1.json` and was fixed before any real fight was simulated.** Later line-ups follow from earlier results,
so the season is one deterministic chain: rendering it again gives the same fights, frame for frame.

## Making the files

```
python scripts/arena_season.py all 1          # episode 1: video, 3 Shorts, thumbnail, roll log
python scripts/arena_season.py all all        # the whole season (about 1-2 hours on 2 cores)
python scripts/arena_season.py video 4 --preview   # quick 960x540 check, fewer simulations
python scripts/arena_season.py meta           # s1_youtube.md + calendar (after the renders)
```

Pushing to the `claude/arena-duel` branch runs `.github/workflows/arena.yml`: every episode renders on its
own runner and everything lands in the draft release **`pit-s1`**, with `s1_youtube.md` (what to paste for
each upload, in calendar order) and `s1_calendar.csv`.

Per episode: `pit-s1eNN.mp4` (1920x1080), `pit-s1eNN-thumbnail.png` (1280x720), `pit-s1eNN-trailer-short.mp4`,
`pit-s1eNN-short-a.mp4`, `pit-s1eNN-short-b.mp4` (1080x1920, with `.cover.png` frames), `pit-s1eNN.rolls.json`
(every roll and event; `pqc.dice.Dice.verify_log(seed, rolls)` replays them) and `pit-s1eNN.chapters.txt`.

## The subscriber system

The aim of the season is subscribers, so every piece is built to turn a viewer into a returning one.

1. **A season with stakes.** The Road to the Bronze Crown: four places, won in episodes 1, 3, 5 and the
   Last Chance Rumble (8), then semifinals and a best-of-7 final. Every episode ends on the Road board
   (who is in, who is next) and an end card naming the next fight and its day. There is always an
   unresolved question one subscription away.
2. **Call it before you watch.** The trailer Short goes out 24 hours early and asks for a pick. The video
   opens with the tale of the tape and the simulated odds and asks again; the pinned comment asks "did you
   call it?". Comments and replies are the strongest signal YouTube reads, and a viewer who picked a side
   comes back to see it settled.
3. **One loop per episode: Short, video, Short, Short.** Trailer (day before), premiere, then two highlights
   (the finish, and the biggest swing of the win chance or a natural 20) on the next days. Every Short's
   *Related video* is its episode; every video's end screen (the last 16 s are drawn with the two frames)
   holds the previous episode or the playlist and the Subscribe button.
4. **Asks timed to the moment.** A subscribe lower-third slides in right after the first initiative roll
   (the viewer has just committed to a side), the Road board carries a subscribe button, and the end card
   another. Never at the very start, never more than three per video.
5. **A milestone with a reward.** Every end card, description and pinned comment says it: 100 subscribers
   unlocks *How many goblins does it take to beat a T-Rex?*. It is already rendered; publish it the week the
   channel crosses the line, and say so in its trailer Short.
6. **Viewers build Season 2.** The final asks for nominations for the Silver Crown (CR 2 and 3: Knight,
   Polar Bear, Allosaurus, Bandit Captain and whoever the comments want). The most-liked nominations get in,
   so the people who nominated have a reason to be subscribed when it starts.
7. **Two shows feeding each other.** Every description points to the daily story, and the arena brings in
   people searching "who would win" who have never heard of an actual play.

### What to measure (YouTube Studio, 48 hours after each upload)

| Upload | Look at | Good sign for a new channel |
|---|---|---|
| Video | Subscribers gained, CTR, average view duration | 1-2 subs per 100 views, CTR 4%+, 50%+ retention |
| Trailer Short | Viewed vs swiped away, comments | 65%+ viewed, picks in the comments |
| Highlight Short | Viewed vs swiped away, related-video clicks | 70%+ viewed |

Compare formats after episode 6 (two of each kind out): whichever of duel, how-many or rumble brings the most
subscribers per 1,000 views gets more slots in Season 2. If trailers beat highlights, cut the third Short;
if highlights beat trailers, post them earlier.

## Rules notes

New engine rules for the arena roster, each covered by `tests/test_arena.py`: Parry (+N AC against a melee hit,
used only when it turns the hit into a miss), Bloodied Fury/Frenzy, charges ("moved 20+ feet straight toward
it"), Rampage, and grapples that restrain. Fighters play by the engine's tactical policy (`pqc/ai.py`) with one arena rule
on top: a fixed Multiattack takes its owed attacks in the best order (the one that knocks Prone first) and
never wastes one on a target out of reach. A few optional actions are never chosen by the AI (Lion's Roar,
Giant Spider's Web, Ghoul's Claw, Allosaurus's Claws); the stat block notes in `data/monsters.json` say which.
Animal and some character sprites are stand-ins from the Ninja Adventure pack (noted in `assets/manifest.json`).
