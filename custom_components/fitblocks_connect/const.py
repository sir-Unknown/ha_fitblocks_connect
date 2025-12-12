"""Constants for the Fitblocks Connect integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform

DOMAIN = "fitblocks_connect"

# Defaults voor configuratie
DEFAULT_BASE_URL = "https://fitblocks.nl"
DEFAULT_BOX = "physicsperformance"

# Platforms
PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR]

# Timeout voor HTTP-calls
REQUEST_TIMEOUT = 30  # seconden

# Coördinator update-interval: rooster poll elke 5 minuten
UPDATE_INTERVAL = timedelta(minutes=30)

# Config keys
CONF_BASE_URL = "base_url"
CONF_BOX = "box"
CONF_DISPLAY_NAME = "display_name"

LOGGER = logging.getLogger(__name__)

# Data fields that should be redacted in diagnostics
TO_REDACT: set[str] = {CONF_PASSWORD, CONF_USERNAME}
