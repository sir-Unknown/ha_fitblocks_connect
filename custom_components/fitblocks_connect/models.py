"""Runtime data models for the Fitblocks Connect integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .client import FitblocksConnectClient
from .coordinator import FitblocksConnectCoordinator


@dataclass(slots=True)
class FitblocksConnectRuntimeData:
    """Runtime container for Fitblocks Connect."""

    client: FitblocksConnectClient
    coordinator: FitblocksConnectCoordinator


type FitblocksConnectConfigEntry = ConfigEntry[FitblocksConnectRuntimeData]
