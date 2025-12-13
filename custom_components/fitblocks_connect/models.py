"""Runtime data models for the Fitblocks Connect integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict

from homeassistant.config_entries import ConfigEntry

from .client import FitblocksConnectClient
from .coordinator import FitblocksConnectCoordinator


class FitblocksScheduleEvent(TypedDict):
    """Single schedule event returned by the Fitblocks Connect API."""

    uniqueId: str
    eventId: str
    classTypeId: str
    title: str
    start: str
    end: str
    subscribed: bool

    color: NotRequired[str]
    totalRegistrations: NotRequired[int]
    totalPossibleRegistrations: NotRequired[int]
    isRecurring: NotRequired[bool]
    isOnWaitingList: NotRequired[bool]
    boxSlug: NotRequired[str]
    workoutId: NotRequired[str | None]
    categoryId: NotRequired[str | None]
    linkAllDay: NotRequired[bool]
    isAdmin: NotRequired[bool]
    creditsCost: NotRequired[int]

    # Enriched fields from classTypeDetails in the coordinator
    description: NotRequired[str]
    participants: NotRequired[list[str]]
    user_first_name: NotRequired[str]
    scheduleRegistrationId: NotRequired[str]
    credits_remaining: NotRequired[int]
    total_possible_registrations: NotRequired[int]
    total_registrations: NotRequired[int]
    total_users_on_waiting_list: NotRequired[int]
    is_full: NotRequired[bool]


class FitblocksScheduleData(TypedDict, total=False):
    """Top-level schedule container returned by the Fitblocks Connect API."""

    events: list[FitblocksScheduleEvent]
    user_first_name: str
    last_known_credits: int


@dataclass(slots=True)
class FitblocksConnectRuntimeData:
    """Runtime container for Fitblocks Connect."""

    client: FitblocksConnectClient
    coordinator: FitblocksConnectCoordinator


type FitblocksConnectConfigEntry = ConfigEntry[FitblocksConnectRuntimeData]
