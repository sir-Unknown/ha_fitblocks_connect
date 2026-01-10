"""Sensor entities for the Fitblocks Connect integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_DISPLAY_NAME, DOMAIN, LOGGER
from .coordinator import FitblocksConnectCoordinator, is_user_enrolled
from .models import FitblocksConnectConfigEntry, FitblocksConnectRuntimeData
from .util import parse_fitblocks_datetime

PARALLEL_UPDATES = 0

MAX_LESSON_SENSORS = 4


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: FitblocksConnectConfigEntry,
    async_add_entities,
) -> None:
    """Set up Fitblocks Connect sensor entities."""
    runtime_data: FitblocksConnectRuntimeData | None = entry.runtime_data
    if runtime_data is None:
        raise RuntimeError("Fitblocks Connect runtime data is not available")
    coordinator: FitblocksConnectCoordinator = runtime_data.coordinator

    display_name_setting = entry.options.get(CONF_DISPLAY_NAME) or entry.data.get(
        CONF_DISPLAY_NAME
    )
    if isinstance(display_name_setting, str) and display_name_setting.strip():
        display_name = display_name_setting.strip()
    else:
        username = entry.data.get(CONF_USERNAME, "")
        display_name = (
            username.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
        )

    entities: list[SensorEntity] = [
        FitblocksConnectCreditsSensor(
            coordinator=coordinator,
            config_entry=entry,
            display_name=display_name,
        ),
        FitblocksConnectEnrolledCountSensor(
            coordinator=coordinator,
            config_entry=entry,
            display_name=display_name,
        ),
        FitblocksConnectLastApiRefreshSensor(
            coordinator=coordinator,
            config_entry=entry,
            display_name=display_name,
        ),
    ]

    entities.extend(
        FitblocksConnectLessonSensor(
            coordinator=coordinator,
            config_entry=entry,
            display_name=display_name,
            index=index,
        )
        for index in range(1, MAX_LESSON_SENSORS + 1)
    )

    async_add_entities(entities)


class BaseFitblocksConnectSensor(
    CoordinatorEntity[FitblocksConnectCoordinator],
    SensorEntity,
):
    """Base class with shared logic."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FitblocksConnectCoordinator,
        config_entry: FitblocksConnectConfigEntry,
        display_name: str,
    ) -> None:
        """Initialize the base Fitblocks Connect sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._display_name = display_name

    @property
    def device_info(self) -> DeviceInfo:
        """Group all sensors under a single service device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._config_entry.entry_id)},
            name=self._display_name,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _events(self) -> list[dict[str, Any]]:
        """Return raw events from the coordinator."""
        data = self.coordinator.data or {}
        raw_events = data.get("events", [])
        if not isinstance(raw_events, list):
            LOGGER.debug("Unexpected schedule JSON structure: %s", type(raw_events))
            return []
        return raw_events

    def _upcoming_enrolled_events(self) -> list[tuple[datetime, dict[str, Any]]]:
        """Return upcoming enrolled events sorted by start time."""
        now = dt_util.utcnow()
        upcoming: list[tuple[datetime, dict[str, Any]]] = []

        for item in self._events:
            if not isinstance(item, dict) or not is_user_enrolled(item):
                continue

            start_str = item.get("start")
            if not isinstance(start_str, str) or not start_str:
                continue

            start = parse_fitblocks_datetime(start_str)
            if start is None:
                continue

            if start < now:
                continue

            upcoming.append((start, item))

        upcoming.sort(key=lambda event: event[0])
        return upcoming

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class FitblocksConnectCreditsSensor(BaseFitblocksConnectSensor):
    """Sensor showing remaining credits."""

    def __init__(
        self,
        coordinator: FitblocksConnectCoordinator,
        config_entry: FitblocksConnectConfigEntry,
        display_name: str,
    ) -> None:
        """Initialize the credits sensor."""
        super().__init__(coordinator, config_entry, display_name)
        self._attr_unique_id = f"{config_entry.entry_id}_credits"
        self._attr_translation_key = "remaining_credits"

    @property
    def native_value(self) -> int | None:
        """Highest known credits remaining across upcoming booked lessons."""
        values: list[int] = []

        for _start, item in self._upcoming_enrolled_events():
            remaining_credits = item.get("credits_remaining")
            if isinstance(remaining_credits, int):
                values.append(remaining_credits)

        if values:
            return max(values)

        fallback = (self.coordinator.data or {}).get("last_known_credits")
        if isinstance(fallback, int):
            return fallback

        return None


class FitblocksConnectEnrolledCountSensor(BaseFitblocksConnectSensor):
    """Sensor showing number of upcoming booked lessons."""

    def __init__(
        self,
        coordinator: FitblocksConnectCoordinator,
        config_entry: FitblocksConnectConfigEntry,
        display_name: str,
    ) -> None:
        """Initialize the enrolled count sensor."""
        super().__init__(coordinator, config_entry, display_name)
        self._attr_unique_id = f"{config_entry.entry_id}_enrolled_count"
        self._attr_translation_key = "enrolled_lessons"

    @property
    def native_value(self) -> int:
        """Number of upcoming lessons the user is enrolled in."""
        return len(self._upcoming_enrolled_events())


class FitblocksConnectLessonSensor(BaseFitblocksConnectSensor):
    """Sensor showing details for a lesson slot."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: FitblocksConnectCoordinator,
        config_entry: FitblocksConnectConfigEntry,
        display_name: str,
        index: int,
    ) -> None:
        """Initialize a sensor representing the Nth upcoming booked lesson."""
        super().__init__(coordinator, config_entry, display_name)
        self._index = index
        self._attr_unique_id = f"{config_entry.entry_id}_lesson_{index}"
        self._attr_translation_key = f"lesson_{index}"

    def _get_event(self) -> dict[str, Any] | None:
        """Return the event for this slot."""
        upcoming = self._upcoming_enrolled_events()
        if len(upcoming) < self._index:
            return None
        return upcoming[self._index - 1][1]

    @property
    def native_value(self) -> datetime | None:
        """Start time for the booked lesson."""
        item = self._get_event()
        if not item:
            return None

        start_str = item.get("start")
        if not isinstance(start_str, str) or not start_str:
            return None

        start = parse_fitblocks_datetime(start_str)
        if start is None:
            return None
        return start

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes for the booked lesson."""
        item = self._get_event()
        start = self.native_value

        end: datetime | None = None
        if item:
            end_str = item.get("end")
            if isinstance(end_str, str) and end_str:
                end = parse_fitblocks_datetime(end_str)

        workout = None
        if item:
            workout = item.get("title") or item.get("name") or item.get("description")
        if not isinstance(workout, str) or not workout:
            workout = None

        description = item.get("description") if item else None
        if not isinstance(description, str) or not description:
            description = None

        total_possible = item.get("total_possible_registrations") if item else None
        total_reg = item.get("total_registrations") if item else None
        waiting = item.get("total_users_on_waiting_list") if item else None

        occupancy: str | None = None
        if isinstance(total_reg, int) and isinstance(total_possible, int):
            occupancy = f"{total_reg}/{total_possible}"
            if isinstance(waiting, int) and waiting > 0:
                occupancy = f"{occupancy} (+{waiting} waiting list)"

        participants = item.get("participants") if item else None
        participants_count = (
            len(participants) if isinstance(participants, list) else None
        )

        return {
            "workout": workout,
            "description": description,
            "location": self._config_entry.title,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "occupancy": occupancy,
            "participants_count": participants_count,
            "credits_remaining": item.get("credits_remaining") if item else None,
            "total_registrations": total_reg,
            "total_possible_registrations": total_possible,
            "total_users_on_waiting_list": waiting,
            "class_type_id": item.get("classTypeId") if item else None,
            "event_id": (item.get("eventId") or item.get("id")) if item else None,
            "schedule_registration_id": item.get("scheduleRegistrationId")
            if item
            else None,
            "index": self._index,
        }


class FitblocksConnectLastApiRefreshSensor(BaseFitblocksConnectSensor):
    """Sensor showing the last time the Fitblocks API was requested."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: FitblocksConnectCoordinator,
        config_entry: FitblocksConnectConfigEntry,
        display_name: str,
    ) -> None:
        """Initialize the last API refresh sensor."""
        super().__init__(coordinator, config_entry, display_name)
        self._attr_unique_id = f"{config_entry.entry_id}_last_api_refresh"
        self._attr_translation_key = "last_api_refresh"

    @property
    def native_value(self) -> datetime | None:
        """Return the last time the API refresh was requested."""
        return self.coordinator.last_request_time
