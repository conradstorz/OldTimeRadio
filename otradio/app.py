"""Wires the pieces together and runs the radio."""

import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime

from otradio.audio import PlaybackError, Player, PygamePlayer, NullPlayer
from otradio.catalog import Catalog, Recording
from otradio.config import Config
from otradio.scheduler import AlternatingScheduler
from otradio.speech import Speaker, make_speaker
from otradio.store import InMemoryStore, JsonMetadataStore, MetadataStore

logger = logging.getLogger(__name__)

GREETING = "welcome to the old time radio project"
POLL_INTERVAL_SECONDS = 1.0
STATS_FILENAME = "otradio-stats.json"


class Radio:
    """The run loop. Holds no policy of its own — it only wires and sequences."""

    def __init__(
        self,
        config: Config,
        catalog: Catalog,
        scheduler: AlternatingScheduler,
        player: Player,
        speaker: Speaker,
        store: MetadataStore,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = datetime.now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._catalog = catalog
        self._scheduler = scheduler
        self._player = player
        self._speaker = speaker
        self._store = store
        self._sleep = sleep
        self._now = now
        self._monotonic = monotonic

    def run(self, max_iterations: int | None = None) -> None:
        """Play recordings until interrupted.

        `max_iterations` exists so the loop can be tested; None means forever.
        """
        self._player.start()
        try:
            self._speaker.say(GREETING)
            logger.info("System time is %s", self._now())
            played = 0
            while max_iterations is None or played < max_iterations:
                played += 1
                self._play_once(self._scheduler.next())
        finally:
            self._store.save()
            self._player.close()

    def _play_once(self, recording: Recording) -> None:
        logger.info(
            "Playing %s (recorded %s)",
            recording.filename,
            recording.release_date or "date unknown",
        )
        try:
            self._player.play(recording.path)
        except PlaybackError as exc:
            logger.warning("%s", exc)
            self._store.record_unavailable(recording.id, self._now())
            self._sleep(POLL_INTERVAL_SECONDS)
            return

        self._store.record_played(recording.id, self._now())
        self._wait_for_end(recording)

    def _wait_for_end(self, recording: Recording) -> None:
        """Wait for the recording to finish on its own.

        max_play_seconds is a watchdog against a wedged file, not the normal
        way a show ends. The old loop counted down from 300 and cut every show
        off after roughly five minutes.
        """
        limit = self._config.max_play_seconds
        deadline = None if limit is None else self._monotonic() + limit

        # At least one poll interval is spent per recording even if the
        # player is never busy (an instantly-finished or unplayable file),
        # so the outer loop can never spin faster than POLL_INTERVAL_SECONDS.
        self._sleep(POLL_INTERVAL_SECONDS)
        while self._player.is_busy():
            if deadline is not None and self._monotonic() >= deadline:
                logger.warning(
                    "%s exceeded the %s second limit; stopping it.",
                    recording.filename,
                    limit,
                )
                self._player.stop()
                return
            self._sleep(POLL_INTERVAL_SECONDS)


def build_radio(config: Config) -> Radio:
    """Assemble a Radio from configuration."""
    catalog = Catalog.from_directory(config.library_dir, config.commercial_marker)
    logger.info(
        "Library: %d recordings (%d shows, %d commercials) in %s",
        len(catalog),
        len(catalog.shows),
        len(catalog.commercials),
        config.library_dir,
    )
    player: Player = (
        NullPlayer() if config.dry_run else PygamePlayer(volume=config.volume)
    )
    # Dry runs keep history in memory so off-device testing never writes
    # into the library.
    store: MetadataStore = (
        InMemoryStore()
        if config.dry_run
        else JsonMetadataStore(config.library_dir / STATS_FILENAME)
    )
    return Radio(
        config=config,
        catalog=catalog,
        scheduler=AlternatingScheduler(catalog),
        player=player,
        speaker=make_speaker(config),
        store=store,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = Config.from_cli(argv)
    try:
        build_radio(config).run()
    except KeyboardInterrupt:
        logger.info("Goodbye.")
        return 0
    except Exception as exc:
        logger.error("%s", exc)
        return 1
    return 0
