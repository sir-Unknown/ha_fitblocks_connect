"""Diagnostics support for the Fitblocks Connect integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator

from .const import TO_REDACT
from .models import FitblocksConnectConfigEntry


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant,
    entry: FitblocksConnectConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics data for a config entry."""
    runtime_data = entry.runtime_data

    diagnostics: dict[str, Any] = {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
    }

    if runtime_data is None:
        diagnostics["coordinator_data"] = None
        diagnostics["client"] = None
        return diagnostics

    coordinator: TimestampDataUpdateCoordinator[Any] = runtime_data.coordinator
    coordinator_data = coordinator.data or {}
    events = coordinator_data.get("events")
    diagnostics["coordinator_data"] = {
        "events_count": len(events) if isinstance(events, list) else None,
        "has_user_first_name": isinstance(coordinator_data.get("user_first_name"), str),
        "last_known_credits": coordinator_data.get("last_known_credits"),
    }
    diagnostics["coordinator_state"] = {
        "last_update_success": coordinator.last_update_success,
        "last_update_success_time": coordinator.last_update_success_time,
    }
    diagnostics["client"] = {
        "base_url": runtime_data.client.base_url,
        "box": runtime_data.client.box,
        "is_logged_in": runtime_data.client.is_logged_in,
        "branding_name": runtime_data.client.branding_name,
    }

    return diagnostics
