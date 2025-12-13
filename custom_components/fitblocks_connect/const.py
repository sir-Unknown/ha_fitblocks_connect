"""Constants for the Fitblocks Connect integration."""

from __future__ import annotations

from datetime import timedelta
import logging
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

# Coordinator update interval: poll schedule every 30 minutes
UPDATE_INTERVAL: Final = timedelta(minutes=30)

# Config keys
CONF_BASE_URL: Final = "base_url"
CONF_BOX: Final = "box"
CONF_DISPLAY_NAME: Final = "display_name"

LOGGER: Final = logging.getLogger(__name__)

# Data fields that should be redacted in diagnostics
TO_REDACT: Final[set[str]] = {CONF_PASSWORD, CONF_USERNAME}
