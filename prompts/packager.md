# Step: YouTube packaging

Write the YouTube metadata for one episode of **Nat 20 Pixels**, a daily pixel-art D&D 5e story where every roll is real and shown on screen.

Call `submit_packaging` exactly once.

## Rules

* `title`: at most 70 characters, in the form `<Episode title> | Nat 20 Pixels C<campaign>E<episode>`. Curiosity, not clickbait; never spoil the episode's twist or who wins a fight.
* `description`: up to ~900 characters of your own text. First two lines: the hook (what's at stake today). Then one short paragraph on the episode without spoilers past its midpoint. Then one line inviting viewers to the wiki. Chapters, credits and the dice-seed line are appended automatically; don't write them.
* `tags`: 10-15 tags: the show, D&D 5e, pixel art, the characters' names and today's places.
* `thumbnail_text`: at most 24 characters, 2-4 punchy words, no episode number.
* `short`: the episode's YouTube Short, cut automatically from the moment quoted under "Short" below (about 40-55 seconds, vertical).
  * `title`: at most 70 characters, `<what happens> | Nat 20 Pixels`. Name the moment, make people curious; it may show the moment itself (that's the point of a Short) but not the episode's ending or twist.
  * `hook`: at most 32 characters, shown in capitals over the first three seconds: a line from the moment or what's at stake (`SHE'S DOWN. ROLL.`).
  * `description`: one or two sentences, at most 300 characters, setting up the moment. A link to the full episode, credits and hashtags are added automatically.
* `thumbnail_moment`: where the thumbnail frame is taken: a scene id (`s3`) or an encounter action (`e1:4` = action 4 of the fight). Pick the most striking image that does not spoil the ending.

## Material

Episode id: {{episode_id}}
Episode title: {{title}}

### Episode summary (public)
{{summary}}

### Script
{{script}}

### Fight action log
{{actions}}

### Short (the moment the Short shows)
{{short_moment}}
{{feedback}}
