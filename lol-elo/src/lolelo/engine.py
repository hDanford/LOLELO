"""The Elo math, and nothing else.

Two functions. Both are pure (no state), which is what lets the rest of the
system stay simple -- and it's what makes the two-tier region behavior fall out
for free (see model.py).
"""


def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability that A beats B under standard Elo (400-point logistic).

    Equal ratings -> 0.5. A 400-point edge -> ~0.91.
    """
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def updated_ratings(
    rating_a: float, rating_b: float, score_a: float, k: float
) -> tuple[float, float]:
    """Return both teams' new ratings after a result.

    `score_a` is A's actual result in [0, 1] -- use 1.0/0.0 for a clean win/loss,
    or a fraction (e.g. games-won ratio) if you'd rather score a Bo5 by margin.

    The update is zero-sum by construction: whatever A gains, B loses. That
    single fact is doing a lot of work -- it's why intra-region games leave a
    region's average rating untouched, and why cross-region games shift it.
    """
    exp_a = expected_score(rating_a, rating_b)
    delta = k * (score_a - exp_a)
    return rating_a + delta, rating_b - delta
