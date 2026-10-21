# Dice

Every roll on the show comes from one seeded generator per episode. The seed is `<episode>-<attempt>` (for example `C01-E001-1`); each die is `HMAC-SHA256(seed, counter)` reduced to the die's size with rejection sampling, so anyone can recompute any roll from its seed and counter. Episodes are never re-rolled; a technical rerun would increase the attempt number and be listed here.

```python
from pqc.dice import Dice
Dice.verify_log(seed, rolls)   # True if every roll matches
```

| Episode | Seed | Attempt | Rolls | Log |
| --- | --- | --- | --- | --- |
| [C1E1 - Lantern Thirty-Seven](episodes/c01-e001.md) | `C01-E001-1` | 1 | 48 | [JSON](rolls/c01-e001.json) |
| [C1E2 - The Goblin Who Talked](episodes/c01-e002.md) | `C01-E002-1` | 1 | 4 | [JSON](rolls/c01-e002.json) |
| [C1E3 - The Empty Housing](episodes/c01-e003.md) | `C01-E003-1` | 1 | 3 | [JSON](rolls/c01-e003.json) |
| [C1E4 - Wolves at the Birches](episodes/c01-e004.md) | `C01-E004-1` | 1 | 38 | [JSON](rolls/c01-e004.json) |
| [C1E5 - The Scout Camp](episodes/c01-e005.md) | `C01-E005-1` | 1 | 32 | [JSON](rolls/c01-e005.json) |
| [C1E6 - First Watch](episodes/c01-e006.md) | `C01-E006-1` | 1 | 2 | [JSON](rolls/c01-e006.json) |
| [C1E7 - The Saint of the Open Hand](episodes/c01-e007.md) | `C01-E007-1` | 1 | 2 | [JSON](rolls/c01-e007.json) |
| [C1E8 - Wending Mill](episodes/c01-e008.md) | `C01-E008-1` | 1 | 51 | [JSON](rolls/c01-e008.json) |
