"""Calendar entity for Fitblocks Connect lessons."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any, cast

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_DISPLAY_NAME, DOMAIN, LOGGER
from .coordinator import FitblocksConnectCoordinator, is_user_enrolled
from .models import (
    FitblocksConnectConfigEntry,
    FitblocksConnectRuntimeData,
    FitblocksScheduleData,
    FitblocksScheduleEvent,
)
from .util import parse_fitblocks_datetime

PARALLEL_UPDATES = 0


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: FitblocksConnectConfigEntry,
    async_add_entities,
) -> None:
    """Set up Fitblocks Connect calendar entity."""
    runtime_data: FitblocksConnectRuntimeData | None = entry.runtime_data
    if runtime_data is None:
        raise HomeAssistantError("Fitblocks Connect runtime data is not available")
    coordinator: FitblocksConnectCoordinator = runtime_data.coordinator

    entity = FitblocksConnectCalendarEntity(
        coordinator=coordinator,
        config_entry=entry,
    )

    async_add_entities([entity])


class FitblocksConnectCalendarEntity(
    CoordinatorEntity[FitblocksConnectCoordinator],
    CalendarEntity,
):
    """Calendar entity representing the Fitblocks Connect schedule."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: FitblocksConnectCoordinator,
        config_entry: FitblocksConnectConfigEntry,
    ) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator)
        self._config_entry = config_entry

        # Full name of the user (service name)
        display_name_setting = config_entry.options.get(
            CONF_DISPLAY_NAME
        ) or config_entry.data.get(CONF_DISPLAY_NAME)
        display_name: str
        if isinstance(display_name_setting, str) and display_name_setting.strip():
            display_name = display_name_setting.strip()
        else:
            username = str(config_entry.data.get(CONF_USERNAME, ""))
            fallback = (
                username.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
            )
            display_name = fallback or "User"
        self._display_name = display_name

        # First name for calendar and event titles
        coordinator_first_name: str | None = None
        if coordinator.data:
            coordinator_first_name = coordinator.data.get("user_first_name")

        fallback_first_name = display_name.split(" ", 1)[0] or "User"
        first_name = (coordinator_first_name or fallback_first_name).strip()

        self._display_first_name = first_name

        # Unique id
        self._attr_unique_id = f"{config_entry.entry_id}_calendar"

        # Use the gym/service name from the config entry title
        service_name = config_entry.title or self._display_name
        self._attr_name = f"{service_name} - {self._display_name}"

        # Location for all events (for example the gym name from the config entry title)
        self._location_name = service_name

    # === Device / service information ===

    @property
    def device_info(self) -> DeviceInfo:
        """Device info, flagged as a service.

        The name here is the person (Firstname Lastname).
        """
        return DeviceInfo(
            identifiers={(DOMAIN, self._config_entry.entry_id)},
            name=self._display_name,
            entry_type=DeviceEntryType.SERVICE,
        )

    # === Calendar API ===

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming event."""
        now = dt_util.utcnow()
        events = list(self._build_events())
        events.sort(key=lambda ev: ev.start)

        current_or_next: CalendarEvent | None = None
        for ev in events:
            if ev.start <= now < ev.end:
                current_or_next = ev
                break
            if ev.start >= now:
                current_or_next = ev
                break

        return current_or_next

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        events = list(self._build_events())

        def _in_range(ev: CalendarEvent) -> bool:
            # Inclusive overlap: ev.end > start_date and ev.start < end_date
            return ev.end > start_date and ev.start < end_date

        return [ev for ev in events if _in_range(ev)]

    async def async_create_event(self, **kwargs: Any) -> None:
        """Disallow creating events via Home Assistant."""
        raise HomeAssistantError("Fitblocks Connect calendar is read-only")

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Disallow deleting events via Home Assistant."""
        raise HomeAssistantError("Fitblocks Connect calendar is read-only")

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Disallow updating events via Home Assistant."""
        raise HomeAssistantError("Fitblocks Connect calendar is read-only")

    def _build_events(self) -> Iterator[CalendarEvent]:
        """Build CalendarEvent objects from coordinator data.

        Data comes from `FitblocksConnectClient.async_get_schedule` plus enrichment
        from classTypeDetails in the coordinator.
        """
        data = cast(FitblocksScheduleData, self.coordinator.data or {})

        raw_events = cast(list[FitblocksScheduleEvent], data.get("events", []))
        if not isinstance(raw_events, list):
            LOGGER.debug("Unexpected schedule JSON structure: %s", type(raw_events))
            return

        # Global first name (fallback)
        global_user_first_name: str | None = data.get("user_first_name")
        if not global_user_first_name:
            global_user_first_name = self._display_first_name

        for item in raw_events:
            if not isinstance(item, dict):
                continue

            # Only show events where the user is enrolled
            if not is_user_enrolled(item):
                continue

            start_str = item.get("start")
            end_str = item.get("end")
            if not isinstance(start_str, str) or not isinstance(end_str, str):
                continue

            start = parse_fitblocks_datetime(start_str)
            end = parse_fitblocks_datetime(end_str)
            if start is None or end is None:
                continue

            # Lesson name from the schedule
            workout_name = (
                item.get("title")
                or item.get("name")
                or item.get("description")
                or "Class"
            )

            # First name from the event, or fall back to global/entry
            user_first_name = item.get("user_first_name") or global_user_first_name

            summary = f"{user_first_name} - {workout_name}"

            # Only include the lesson description, without extra info
            description = item.get("description") or ""

            uid = (
                item.get("uniqueId")
                or item.get("eventId")
                or item.get("scheduleRegistrationId")
                or None
            )

            yield CalendarEvent(
                start=start,
                end=end,
                summary=summary,
                description=description,
                uid=uid,
                location=self._location_name,
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
