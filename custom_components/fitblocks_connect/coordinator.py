"""Data update coordinator for the Fitblocks Connect integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .client import (
    FitblocksConnectAuthError,
    FitblocksConnectClient,
    FitblocksConnectError,
)
from .const import DOMAIN, LOGGER, UPDATE_INTERVAL
from .util import parse_fitblocks_datetime

MAX_CONCURRENT_EVENT_DETAIL_REQUESTS = 4


def is_user_enrolled(event: Mapping[str, Any]) -> bool:
    """Determine whether an event is booked by the user.

    The Fitblocks schedule API uses the boolean `subscribed` field to indicate
    whether the user is enrolled for an event.
    """
    return event.get("subscribed") is True


class FitblocksConnectCoordinator(
    TimestampDataUpdateCoordinator[dict[str, Any]],
):
    """Coordinator that fetches the schedule and enriches it with classTypeDetails."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: FitblocksConnectClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            name=f"{DOMAIN} schedule",
            config_entry=config_entry,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self._last_known_credits: int | None = None
        self._detail_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EVENT_DETAIL_REQUESTS)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch schedule data via schedule/json and enrich it with lesson details."""
        now: datetime = dt_util.utcnow()
        end: datetime = now + timedelta(days=7)

        LOGGER.debug(
            "FitblocksConnectCoordinator: fetching schedule now=%s end=%s",
            now,
            end,
        )

        data = await self._async_fetch_schedule(now, end)
        await self._async_enrich_events(data, now)
        return data

    async def _async_fetch_schedule(
        self, start: datetime, end: datetime
    ) -> dict[str, Any]:
        """Fetch the base schedule data from the API."""
        try:
            return await self.client.async_get_schedule(start=start, end=end)

        except FitblocksConnectAuthError as err:
            raise ConfigEntryAuthFailed from err

        except FitblocksConnectError as err:
            raise UpdateFailed(
                f"Error communicating with Fitblocks Connect API: {err}"
            ) from err

        except Exception as err:
            LOGGER.exception("Unexpected error in FitblocksConnectCoordinator")
            raise UpdateFailed("Unexpected error") from err

    async def _async_enrich_events(self, data: dict[str, Any], now: datetime) -> None:
        """Fetch per-event details and update the cached schedule data."""
        raw_events: list[dict[str, Any]] = data.get("events", [])
        if not isinstance(raw_events, list):
            LOGGER.debug(
                "Unexpected schedule JSON structure in coordinator: %s",
                type(raw_events),
            )
            return

        tasks, event_refs = self._build_detail_tasks(raw_events, now)
        credits_values: list[int] = []

        if tasks:
            LOGGER.debug(
                "FitblocksConnectCoordinator: fetching classTypeDetails for %s events",
                len(tasks),
            )
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._merge_event_details(
                event_refs,
                results,
                credits_values,
                user_email=(self.client.user_email or "").lower(),
            )

        self._store_user_first_name(data, raw_events)
        self._update_last_known_credits(data, credits_values)

    def _build_detail_tasks(
        self,
        raw_events: list[dict[str, Any]],
        now: datetime,
    ) -> tuple[list[asyncio.Task], list[dict[str, Any]]]:
        """Create classTypeDetails tasks for enrolled or fallback events."""
        tasks: list[asyncio.Task] = []
        event_refs: list[dict[str, Any]] = []

        for item in raw_events:
            if not isinstance(item, dict) or not is_user_enrolled(item):
                continue

            prepared = self._prepare_event_detail_call(item)
            if prepared is None:
                continue

            event_refs.append(item)
            tasks.append(self._create_detail_task(*prepared))

        if tasks:
            return tasks, event_refs

        fallback = self._select_fallback_event(raw_events, now)
        if fallback is None:
            return tasks, event_refs

        ref, prepared = fallback
        event_refs.append(ref)
        tasks.append(self._create_detail_task(*prepared))
        return tasks, event_refs

    def _prepare_event_detail_call(
        self, event: dict[str, Any]
    ) -> tuple[str, str, datetime, datetime] | None:
        """Validate raw event data and return parameters for detail calls."""
        class_type_id = event.get("classTypeId")
        event_id = event.get("eventId") or event.get("id")
        start_str = event.get("start")
        end_str = event.get("end")

        if not class_type_id or not event_id or not start_str or not end_str:
            return None

        if not isinstance(start_str, str) or not isinstance(end_str, str):
            return None

        start_dt = parse_fitblocks_datetime(start_str)
        end_dt = parse_fitblocks_datetime(end_str)
        if start_dt is None or end_dt is None:
            return None

        return class_type_id, str(event_id), start_dt, end_dt

    def _select_fallback_event(
        self,
        raw_events: list[dict[str, Any]],
        now: datetime,
    ) -> tuple[dict[str, Any], tuple[str, str, datetime, datetime]] | None:
        """Return the soonest upcoming event to keep credits info populated."""
        fallback_ref: dict[str, Any] | None = None
        fallback_prepared: tuple[str, str, datetime, datetime] | None = None
        fallback_start: datetime | None = None

        for item in raw_events:
            if not isinstance(item, dict):
                continue

            prepared = self._prepare_event_detail_call(item)
            if prepared is None:
                continue

            _, _, start_dt, _ = prepared
            if start_dt < now:
                continue

            if fallback_start is None or start_dt < fallback_start:
                fallback_ref = item
                fallback_prepared = prepared
                fallback_start = start_dt

        if fallback_ref is None or fallback_prepared is None:
            return None

        return fallback_ref, fallback_prepared

    def _create_detail_task(
        self,
        class_type_id: str,
        event_id: str,
        start: datetime,
        end: datetime,
    ) -> asyncio.Task:
        """Create an async task to fetch class type details."""
        return asyncio.create_task(
            self._async_get_class_type_details_limited(
                class_type_id=class_type_id,
                event_id=event_id,
                start=start,
                end=end,
            )
        )

    async def _async_get_class_type_details_limited(
        self,
        class_type_id: str,
        event_id: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """Fetch class type details with a concurrency limit."""
        async with self._detail_semaphore:
            return await self.client.async_get_class_type_details(
                class_type_id=class_type_id,
                event_id=event_id,
                start=start,
                end=end,
            )

    def _merge_event_details(
        self,
        event_refs: list[dict[str, Any]],
        results: list[Any],
        credits_values: list[int],
        user_email: str,
    ) -> None:
        """Merge fetched classTypeDetails into the cached schedule data."""
        for item, result in zip(event_refs, results, strict=False):
            if isinstance(result, Exception) or not isinstance(result, dict):
                if isinstance(result, Exception):
                    LOGGER.debug(
                        "Error fetching classTypeDetails for event %s: %s",
                        item,
                        result,
                    )
                continue

            desc = result.get("description")
            if desc:
                item["description"] = desc

            mapping: dict[str, str] = {
                "creditsRemaining": "credits_remaining",
                "totalPossibleRegistrations": "total_possible_registrations",
                "totalRegistrations": "total_registrations",
                "totalUsersOnWaitingList": "total_users_on_waiting_list",
                "isFull": "is_full",
            }
            for src, dest in mapping.items():
                if src in result:
                    item[dest] = result[src]
                    if dest == "credits_remaining" and isinstance(result[src], int):
                        credits_values.append(result[src])

            schedule_registration_id = result.get("scheduleRegistrationId")
            if schedule_registration_id:
                item["scheduleRegistrationId"] = schedule_registration_id

            participants: list[str] = []
            for user in result.get("signedUpUsers", []):
                if not isinstance(user, dict):
                    continue
                first = (user.get("first_name") or "").strip()
                last = (user.get("surname") or "").strip()
                full = (first + " " + last).strip()
                if full:
                    participants.append(full)
            if participants:
                item["participants"] = participants

            if user_email:
                my_first_name = self._extract_user_first_name(result, user_email)
                if my_first_name:
                    item["user_first_name"] = my_first_name
            elif schedule_registration_id:
                my_first_name = self._extract_user_first_name_by_registration_id(
                    result, schedule_registration_id
                )
                if my_first_name:
                    item["user_first_name"] = my_first_name

    @staticmethod
    def _extract_user_first_name(result: dict[str, Any], user_email: str) -> str | None:
        """Return the first name for the logged-in user from classTypeDetails."""
        for athlete in result.get("athletes", []):
            if not isinstance(athlete, dict):
                continue
            email = (athlete.get("email") or "").lower()
            if email == user_email:
                return athlete.get("first_name") or None
        return None

    @staticmethod
    def _extract_user_first_name_by_registration_id(
        result: dict[str, Any], schedule_registration_id: str
    ) -> str | None:
        """Return the first name for the logged-in user from classTypeDetails."""
        for user in result.get("signedUpUsers", []):
            if not isinstance(user, dict):
                continue
            user_registration_id = user.get("schedule_registration_id")
            if user_registration_id != schedule_registration_id:
                continue
            first_name = user.get("first_name")
            return first_name if isinstance(first_name, str) and first_name else None
        return None

    @staticmethod
    def _store_user_first_name(
        data: dict[str, Any], events: list[dict[str, Any]]
    ) -> None:
        """Promote the detected user first name to the top-level payload."""
        for item in events:
            if not isinstance(item, dict):
                continue
            first_name = item.get("user_first_name")
            if first_name:
                data["user_first_name"] = first_name
                return

    def _update_last_known_credits(
        self,
        data: dict[str, Any],
        credits_values: list[int],
    ) -> None:
        """Update cached credits based on the latest fetch."""
        if credits_values:
            last_known_credits = max(credits_values)
            data["last_known_credits"] = last_known_credits
            self._last_known_credits = last_known_credits
            return

        if self._last_known_credits is not None:
            data["last_known_credits"] = self._last_known_credits
