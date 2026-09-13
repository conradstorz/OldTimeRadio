"""Decides what plays next."""

import logging
import random

from otradio.catalog import Catalog, Recording

logger = logging.getLogger(__name__)


class EmptyLibrary(Exception):
    """There is nothing at all to play."""


class AlternatingScheduler:
    """Alternates shows and commercials.

    Draws from the catalog's pre-partitioned lists rather than sampling at
    random until the right type turns up, so a library with only one kind of
    recording can never hang the radio.
    """

    def __init__(
        self,
        catalog: Catalog,
        rng: random.Random | None = None,
        era: int | None = None,
    ) -> None:
        self._catalog = catalog
        self._rng = rng if rng is not None else random.Random()
        self._era = era
        self._want_commercial = False
        self._warned_about_missing: set[str] = set()

    @property
    def era(self) -> int | None:
        return self._era

    def cycle_era(self) -> int | None:
        """Advance the era: all -> oldest decade -> ... -> newest -> all."""
        cycle: list[int | None] = [None, *self._catalog.decades]
        position = cycle.index(self._era) if self._era in cycle else 0
        self._era = cycle[(position + 1) % len(cycle)]
        return self._era

    def next(self) -> Recording:
        shows = self._catalog.shows_for(self._era)
        commercials = self._catalog.commercials
        if not shows and not commercials:
            raise EmptyLibrary("The recordings library contains nothing playable.")

        wanted = commercials if self._want_commercial else shows
        if wanted:
            self._want_commercial = not self._want_commercial
            return self._rng.choice(wanted)

        # The bucket we wanted is empty. Play the other kind continuously
        # rather than stalling, and do not toggle: every later call lands here
        # too, which is the point.
        self._warn_once("commercials" if self._want_commercial else "shows")
        fallback = shows if shows else commercials
        return self._rng.choice(fallback)

    def _warn_once(self, missing: str) -> None:
        if missing in self._warned_about_missing:
            return
        self._warned_about_missing.add(missing)
        logger.warning(
            "No %s in the library; playing the remaining recordings continuously.",
            missing,
        )
