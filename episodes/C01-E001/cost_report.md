# Claude API cost per episode (from the C01-E001 ledger)

Measured tokens (estimated offline):

| Step | Model | Input | Cache write | Cache read | Output |
| --- | --- | --- | --- | --- | --- |
| plan | claude-sonnet-5-5 | 4,240 | 22,853 | 0 | 2,675 |
| script | claude-opus-5-5 | 8,018 | 22,853 | 0 | 3,008 |
| continuity | claude-haiku-4-5-20251001 | 9,495 | 22,853 | 0 | 199 |
| wiki_facts | claude-haiku-4-5-20251001 | 5,381 | 6,911 | 0 | 1,452 |
| packaging | claude-haiku-4-5-20251001 | 4,034 | 0 | 6,911 | 320 |

| Scenario | USD per episode |
| --- | --- |
| Premiere / finale (Opus 5.5 writes), measured | $0.183 |
| Ordinary episode (Sonnet 5.5 writes, shared cache) | $0.105 |
| Ordinary episode with one rewrite | $0.137 |
| Ordinary episode, no Batch API | $0.210 |
| Ordinary episode, no Batch API, no caching | $0.238 |

| Projection | USD |
| --- | --- |
| Blended episode (5% premieres, 20% rewrites) | $0.115 |
| Month (22 weekday episodes) | $2.53 |
| Campaign planner, per campaign (Fable 5.1, batch) | $0.97 |
| Whole series (474 episodes + 19 campaign plans) | $72.93 |

Prices: USD per million tokens from `pqc/pipeline/claude.py` (Batch API -50%). Offline token counts are estimated at 3.2 characters per token; a live run records the API's own usage figures.
