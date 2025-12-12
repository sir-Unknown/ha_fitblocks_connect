"""Sensor entities for the Fitblocks Connect integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_DISPLAY_NAME, DOMAIN, LOGGER
from .coordinator import FitblocksConnectCoordinator
from .models import FitblocksConnectConfigEntry, FitblocksConnectRuntimeData

PARALLEL_UPDATES = 0


def _slug_from_name(name: str | None) -> str:
    """Maak een simpele slug van een naam."""
    if not name:
        return "user"
    return name.strip().lower().replace(" ", "_")


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

    # Volledige naam (persoon) uit config
    display_name = entry.data.get(CONF_DISPLAY_NAME)
    if not display_name:
        username = entry.data.get("username", "")
        display_name = (
            username.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
        )

    # Voornaam (eerste deel) voor titels en entity-id-slug
    display_first_name = display_name.split(" ", 1)[0] or display_name
    first_name_slug = _slug_from_name(display_first_name)

    entities: list[SensorEntity] = []

    # Globale sensoren
    entities.append(
        FitblocksConnectCreditsSensor(
            coordinator=coordinator,
            config_entry=entry,
            display_name=display_name,
            display_first_name=display_first_name,
            first_name_slug=first_name_slug,
        )
    )
    entities.append(
        FitblocksConnectEnrolledCountSensor(
            coordinator=coordinator,
            config_entry=entry,
            display_name=display_name,
            display_first_name=display_first_name,
            first_name_slug=first_name_slug,
        )
    )

    # Per-les sensoren, voor komende ingeschreven lessen
    now = dt_util.utcnow()
    raw_events = coordinator.data.get("events", []) if coordinator.data else []
    if not isinstance(raw_events, list):
        raw_events = []

    events_for_sensors: list[tuple[datetime, dict[str, Any]]] = []

    for item in raw_events:
        if not isinstance(item, dict):
            continue

        if not item.get("subscribed"):
            continue

        start_str = item.get("start")
        if not start_str:
            continue

        start = dt_util.parse_datetime(start_str)
        if start is None:
            continue

        if start.tzinfo is None:
            start = start.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        start = dt_util.as_utc(start)

        if start < now:
            continue

        events_for_sensors.append((start, item))

    events_for_sensors.sort(key=lambda x: x[0])

    for idx, (start, item) in enumerate(events_for_sensors, start=1):
        event_key = item.get("eventId") or item.get("id") or start.isoformat()
        entities.append(
            FitblocksConnectLessonSensor(
                coordinator=coordinator,
                config_entry=entry,
                display_name=display_name,
                display_first_name=display_first_name,
                first_name_slug=first_name_slug,
                index=idx,
                event_key=str(event_key),
            )
        )

    async_add_entities(entities)


class BaseFitblocksConnectSensor(
    CoordinatorEntity[FitblocksConnectCoordinator],
    SensorEntity,
):
    """Basisklasse met gedeelde logica."""

    # Zelf volledige naam zetten; niet automatisch "device – entity".
    _attr_has_entity_name = False

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
        """Laat alle sensoren onder dezelfde dienst vallen."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._config_entry.entry_id)},
            name=self._display_name,  # Voornaam Achternaam
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _events(self) -> list[dict[str, Any]]:
        """Handige helper: lijst met ruwe events uit de coordinator."""
        data = self.coordinator.data or {}
        raw_events = data.get("events", [])
        if not isinstance(raw_events, list):
            LOGGER.debug("Unexpected schedule JSON structure: %s", type(raw_events))
            return []
        return raw_events

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class FitblocksConnectCreditsSensor(BaseFitblocksConnectSensor):
    """Sensor met resterende credits."""

    def __init__(
        self,
        coordinator: FitblocksConnectCoordinator,
        config_entry: FitblocksConnectConfigEntry,
        display_name: str,
        display_first_name: str,
        first_name_slug: str,
    ) -> None:
        """Initialize the credits sensor."""
        super().__init__(coordinator, config_entry, display_name)
        self._display_first_name = display_first_name
        self._first_name_slug = first_name_slug

        self._attr_unique_id = f"{config_entry.entry_id}_credits"
        # Alleen de naam van de sensor, zonder "User –"
        self._attr_name = "Resterende credits"
        # Entity-id met gewenst patroon
        self.entity_id = f"sensor.fitblocks_connect_{first_name_slug}_credits"

    @property
    def native_value(self) -> int | None:
        """Hoogste bekende creditsRemaining over komende ingeschreven lessen."""
        now = dt_util.utcnow()
        values: list[int] = []

        for item in self._events:
            if not isinstance(item, dict):
                continue
            if not item.get("subscribed"):
                continue

            start_str = item.get("start")
            if not start_str:
                continue

            start = dt_util.parse_datetime(start_str)
            if start is None:
                continue

            if start.tzinfo is None:
                start = start.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            start = dt_util.as_utc(start)

            if start < now:
                continue

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
    """Sensor met het aantal komende ingeschreven lessen."""

    def __init__(
        self,
        coordinator: FitblocksConnectCoordinator,
        config_entry: FitblocksConnectConfigEntry,
        display_name: str,
        display_first_name: str,
        first_name_slug: str,
    ) -> None:
        """Initialize the enrolled count sensor."""
        super().__init__(coordinator, config_entry, display_name)
        self._display_first_name = display_first_name
        self._first_name_slug = first_name_slug

        self._attr_unique_id = f"{config_entry.entry_id}_enrolled_count"
        # Gewoon "Ingeschreven lessen"
        self._attr_name = "Ingeschreven lessen"
        self.entity_id = f"sensor.fitblocks_connect_{first_name_slug}_enrolled_count"

    @property
    def native_value(self) -> int:
        """Aantal komende lessen waarvoor 'subscribed' == True."""
        now = dt_util.utcnow()
        count = 0

        for item in self._events:
            if not isinstance(item, dict):
                continue
            if not item.get("subscribed"):
                continue

            start_str = item.get("start")
            if not start_str:
                continue

            start = dt_util.parse_datetime(start_str)
            if start is None:
                continue

            if start.tzinfo is None:
                start = start.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            start = dt_util.as_utc(start)

            if start < now:
                continue

            count += 1

        return count


class FitblocksConnectLessonSensor(BaseFitblocksConnectSensor):
    """Sensor voor één ingeschreven les.

    State = starttijd van de les (datetime), attributes bevatten de rest.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: FitblocksConnectCoordinator,
        config_entry: FitblocksConnectConfigEntry,
        display_name: str,
        display_first_name: str,
        first_name_slug: str,
        index: int,
        event_key: str,
    ) -> None:
        """Initialize a sensor representing a single booked lesson."""
        super().__init__(coordinator, config_entry, display_name)
        self._display_first_name = display_first_name
        self._first_name_slug = first_name_slug
        self._index = index
        self._event_key = event_key

        self._attr_unique_id = f"{config_entry.entry_id}_lesson_{index}"
        # Simpel: "Les 1", "Les 2", ...
        self._attr_name = f"Les {index}"
        # Entity-id: sensor.fitblocks_connect_{voornaam}_event_{index}
        self.entity_id = f"sensor.fitblocks_connect_{first_name_slug}_event_{index}"

    def _get_event(self) -> dict[str, Any] | None:
        """Zoek het event met deze event_key in de coordinator-data."""
        for item in self._events:
            if not isinstance(item, dict):
                continue
            key = item.get("eventId") or item.get("id")
            if not key:
                continue
            if str(key) == self._event_key:
                return item
        return None

    @property
    def native_value(self) -> datetime | None:
        """Starttijd van de les als datetime (TIMESTAMP)."""
        item = self._get_event()
        if not item:
            return None

        start_str = item.get("start")
        if not start_str:
            return None

        start = dt_util.parse_datetime(start_str)
        if start is None:
            return None

        if start.tzinfo is None:
            start = start.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(start)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attribuutset met alle info over deze les."""
        item = self._get_event()
        if not item:
            return {}

        start_str = item.get("start")
        end_str = item.get("end")

        start: datetime | None = None
        end: datetime | None = None

        if start_str:
            start = dt_util.parse_datetime(start_str)
            if start is not None:
                if start.tzinfo is None:
                    start = start.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                start = dt_util.as_utc(start)

        if end_str:
            end = dt_util.parse_datetime(end_str)
            if end is not None:
                if end.tzinfo is None:
                    end = end.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                end = dt_util.as_utc(end)

        workout_name = (
            item.get("title") or item.get("name") or item.get("description") or "Les"
        )

        # Eerste naam voor in de titel (zoals in de kalender)
        user_first_name = item.get("user_first_name") or self._display_first_name

        location = self._config_entry.title  # Bar's Gym

        base_desc = item.get("description") or ""

        remaining_credits = item.get("credits_remaining")
        total_possible = item.get("total_possible_registrations")
        total_reg = item.get("total_registrations")
        waiting = item.get("total_users_on_waiting_list")

        bezetting: str | None = None
        if isinstance(total_reg, int) and isinstance(total_possible, int):
            bezetting = f"{total_reg}/{total_possible}"
            if isinstance(waiting, int) and waiting > 0:
                bezetting += f" (+{waiting} wachtlijst)"

        participants = item.get("participants") or []

        title = f"{user_first_name} – {workout_name}"

        return {
            "title": title,
            "workout": workout_name,
            "location": location,
            "description": base_desc,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "bezetting": bezetting,
            "credits_remaining": remaining_credits,
            "total_registrations": total_reg,
            "total_possible_registrations": total_possible,
            "total_users_on_waiting_list": waiting,
            "deelnemers": participants,
            "class_type_id": item.get("classTypeId"),
            "event_id": item.get("eventId") or item.get("id"),
            "schedule_registration_id": item.get("scheduleRegistrationId"),
            "index": self._index,
        }
