# Dice

Every roll on the show comes from one seeded generator per episode. The seed is `<episode>-<attempt>` (for example `C01-E001-1`); each die is `HMAC-SHA256(seed, counter)` reduced to the die's size with rejection sampling, so anyone can recompute any roll from its seed and counter. Episodes are never re-rolled; a technical rerun would increase the attempt number and be listed here.

```python
from pqc.dice import Dice
Dice.verify_log(seed, rolls)   # True if every roll matches
```

| Episode | Seed | Attempt | Rolls | Log |
| --- | --- | --- | --- | --- |
