"""
Small in-memory reference evaluators for the ordered-set aggregates
``PERCENTILE_CONT`` and ``PERCENTILE_DISC``.

These helpers do not talk to a database.  They implement the semantics
described in the PostgreSQL documentation
(https://www.postgresql.org/docs/current/functions-aggregate.html) so that the
difference between continuous and discrete percentiles can be demonstrated on
the same input data:

* ``percentile_cont`` (linear interpolation) ::

      position  = (N - 1) * fraction
      lower     = floor(position)
      result    = sorted[lower] + (sorted[lower + 1] - sorted[lower])
                  * (position - lower)

* ``percentile_disc`` (nearest stored value) ::

      result = the first value in sorted order whose cumulative distribution
               (rank / N) is greater than or equal to ``fraction``

``None`` values are ignored, matching the way ordered-set aggregates order
their input (``NULL`` values do not participate in the percentile).
"""

from __future__ import annotations

from typing import Sequence

__author__ = "Timothy Heys"
__email__ = "theys@kayak.com"


def _prepare(values: Sequence[float], fraction: float) -> tuple[list[float], int]:
    if not 0 <= fraction <= 1:
        raise ValueError("Percentile fraction must be between 0 and 1")

    ordered = sorted(value for value in values if value is not None)
    count = len(ordered)
    if count == 0:
        raise ValueError("Cannot compute a percentile without any non-null values")

    return ordered, count


def percentile_cont(fraction: float, values: Sequence[float]) -> float:
    """
    Reference implementation of ``PERCENTILE_CONT`` (continuous percentile).

    Linearly interpolates between the two values surrounding the percentile
    position, so the result does not have to be a value that appears in the
    input.

    :param fraction: percentile in the closed interval ``[0, 1]``.
    :param values: input sample; ``None`` entries are ignored.
    :return: the interpolated percentile.
    """
    ordered, count = _prepare(values, fraction)

    position = (count - 1) * fraction
    lower_index = int(position)
    if lower_index == count - 1:
        return float(ordered[lower_index])

    lower_value = ordered[lower_index]
    upper_value = ordered[lower_index + 1]
    return float(lower_value + (upper_value - lower_value) * (position - lower_index))


def percentile_disc(fraction: float, values: Sequence[float]) -> float:
    """
    Reference implementation of ``PERCENTILE_DISC`` (discrete percentile).

    Returns the first value from the (ascending) ordered set whose cumulative
    distribution ``rank / N`` is greater than or equal to ``fraction``.  The
    result is always a value that actually appears in the input.

    :param fraction: percentile in the closed interval ``[0, 1]``.
    :param values: input sample; ``None`` entries are ignored.
    :return: the discrete percentile.
    """
    ordered, count = _prepare(values, fraction)

    for rank, value in enumerate(ordered, start=1):
        if rank / count >= fraction:
            return float(value)

    # fraction == 1 and floating point rounds short: return the maximum.
    return float(ordered[-1])
