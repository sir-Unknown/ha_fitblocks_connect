"""Constants for the Fitblocks Connect integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Final

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform

DOMAIN: Final = "fitblocks_connect"

# Defaults for configuration
DEFAULT_BASE_URL: Final = "https://fitblocks.nl"
DEFAULT_BOX: Final = "physicsperformance"

# Platforms
PLATFORMS: Final[list[Platform]] = [Platform.CALENDAR, Platform.SENSOR]

# Timeout for HTTP calls
REQUEST_TIMEOUT: Final[float] = 30  # seconds

# Coordinator update intervals: faster during daytime, slower overnight
UPDATE_INTERVAL_DAY: Final = timedelta(minutes=5)
UPDATE_INTERVAL_NIGHT: Final = timedelta(minutes=30)

# Daytime window for faster updates (local time, 24h clock)
DAYTIME_START_HOUR: Final = 8
DAYTIME_END_HOUR: Final = 21

# Config keys
CONF_BASE_URL: Final = "base_url"
CONF_BOX: Final = "box"
CONF_DISPLAY_NAME: Final = "display_name"

LOGGER: Final = logging.getLogger(__name__)

# Data fields that should be redacted in diagnostics
TO_REDACT: Final[set[str]] = {CONF_PASSWORD, CONF_USERNAME}
