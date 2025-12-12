"""Fitblocks Connect integration setup."""

from __future__ import annotations

from typing import cast

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import (
    FitblocksConnectAuthError,
    FitblocksConnectClient,
    FitblocksConnectError,
)
from .const import CONF_BASE_URL, CONF_BOX, DOMAIN, LOGGER, PLATFORMS
from .coordinator import FitblocksConnectCoordinator
from .models import FitblocksConnectConfigEntry, FitblocksConnectRuntimeData


async def async_setup(_hass: HomeAssistant, _config: dict) -> bool:
    """Set up via YAML (niet gebruikt, alleen config entries)."""
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: FitblocksConnectConfigEntry
) -> bool:
    """Set up fitblocks_connect vanaf een config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data["entry_count"] = domain_data.get("entry_count", 0) + 1

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    base_url: str = entry.data[CONF_BASE_URL]
    box: str = entry.data[CONF_BOX]
    username: str = entry.data["username"]
    password: str = entry.data["password"]

    session = async_get_clientsession(hass)
    client = FitblocksConnectClient(
        hass=hass,
        session=session,
        base_url=base_url,
        box=box,
        username=username,
        password=password,
    )

    coordinator = FitblocksConnectCoordinator(
        hass=hass,
        config_entry=entry,
        client=client,
    )

    await coordinator.async_config_entry_first_refresh()

    runtime_data = FitblocksConnectRuntimeData(
        client=client,
        coordinator=coordinator,
    )
    entry.runtime_data = runtime_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await _async_register_services(hass)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: FitblocksConnectConfigEntry
) -> bool:
    """Unload een config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        domain_data = hass.data.get(DOMAIN)
        if domain_data:
            domain_data["entry_count"] = max(
                0, domain_data.get("entry_count", 1) - 1
            )
            if domain_data.get("entry_count", 0) == 0:
                await _async_unregister_services(hass)

    return unload_ok


async def _async_register_services(hass: HomeAssistant) -> None:
    """Domeinservices registreren (eenmalig)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("services_registered"):
        return

    LOGGER.debug("Registering fitblocks_connect services")

    async def _async_get_single_entry_data() -> FitblocksConnectRuntimeData:
        """De enige config entry data voor dit domein pakken."""
        entries = _async_loaded_runtime_data(hass)
        if not entries:
            raise HomeAssistantError("fitblocks_connect is not configured")
        return entries[0]

    async def handle_enroll(call: ServiceCall) -> None:
        """Service fitblocks_connect.enroll."""
        entry_data = await _async_get_single_entry_data()
        client: FitblocksConnectClient = entry_data.client
        coordinator: FitblocksConnectCoordinator = entry_data.coordinator

        start = call.data["start"]
        end = call.data["end"]
        class_type_id = call.data["class_type_id"]

        try:
            status = await client.async_enroll(
                start=start,
                end=end,
                class_type_id=class_type_id,
            )
            LOGGER.info("Enroll status: %s", status)
        except FitblocksConnectAuthError as err:
            raise HomeAssistantError(f"Authentication failed: {err}") from err
        except FitblocksConnectError as err:
            raise HomeAssistantError(f"Enroll failed: {err}") from err

        await coordinator.async_request_refresh()

    async def handle_unenroll(call: ServiceCall) -> None:
        """Service fitblocks_connect.unenroll."""
        entry_data = await _async_get_single_entry_data()
        client: FitblocksConnectClient = entry_data.client
        coordinator: FitblocksConnectCoordinator = entry_data.coordinator

        schedule_registration_id = call.data["schedule_registration_id"]
        class_type_id = call.data["class_type_id"]

        try:
            success = await client.async_unenroll(
                schedule_registration_id=schedule_registration_id,
                class_type_id=class_type_id,
            )
            LOGGER.info("Unenroll success=%s", success)
        except FitblocksConnectAuthError as err:
            raise HomeAssistantError(f"Authentication failed: {err}") from err
        except FitblocksConnectError as err:
            raise HomeAssistantError(f"Unenroll failed: {err}") from err

        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        "enroll",
        handle_enroll,
        schema=vol.Schema(
            {
                vol.Required("start"): cv.datetime,
                vol.Required("end"): cv.datetime,
                vol.Required("class_type_id"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "unenroll",
        handle_unenroll,
        schema=vol.Schema(
            {
                vol.Required("schedule_registration_id"): cv.string,
                vol.Required("class_type_id"): cv.string,
            }
        ),
    )

    domain_data["services_registered"] = True


async def _async_unregister_services(hass: HomeAssistant) -> None:
    """Services verwijderen als er geen entries meer zijn."""
    domain_data = hass.data.get(DOMAIN)
    if not domain_data or not domain_data.get("services_registered"):
        return

    hass.services.async_remove(DOMAIN, "enroll")
    hass.services.async_remove(DOMAIN, "unenroll")
    domain_data["services_registered"] = False


async def _async_reload_entry(
    hass: HomeAssistant, entry: FitblocksConnectConfigEntry
) -> None:
    """Herlaad de config entry na optieswijzigingen."""

    await hass.config_entries.async_reload(entry.entry_id)


def _async_loaded_runtime_data(
    hass: HomeAssistant,
) -> list[FitblocksConnectRuntimeData]:
    """Return runtime data objects for loaded entries."""
    entries = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        if entry.runtime_data is None:
            continue
        entries.append(cast(FitblocksConnectRuntimeData, entry.runtime_data))
    return entries
