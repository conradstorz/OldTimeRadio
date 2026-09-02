"""Old time radio player.

Plays recordings of old radio shows, interleaved with period commercials, on a
Raspberry Pi installed in a 1940s radio cabinet.
"""

from otradio.app import Radio, build_radio, main
from otradio.config import Config

__all__ = ["Config", "Radio", "build_radio", "main"]
