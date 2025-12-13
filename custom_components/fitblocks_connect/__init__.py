"""Fitblocks Connect integration setup."""

from __future__ import annotations

from typing import cast

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
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

MIGRATION_MINOR_VERSION = 2


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up the Fitblocks Connect integration."""
    await _async_register_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: FitblocksConnectConfigEntry
) -> bool:
    """Set up Fitblocks Connect from a config entry."""
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    base_url: str = entry.data[CONF_BASE_URL]
    box: str = entry.data[CONF_BOX]
    username: str = entry.data[CONF_USERNAME]
    password: str = entry.data[CONF_PASSWORD]

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

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: FitblocksConnectConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry data to the current format."""
    if entry.domain != DOMAIN:
        return False

    if entry.minor_version >= MIGRATION_MINOR_VERSION:
        return True

    data = dict(entry.data)
    options = dict(entry.options)

    if (
        display_name := data.pop("display_name", None)
    ) and "display_name" not in options:
        options["display_name"] = display_name

    if CONF_USERNAME not in data and (username := data.pop("username", None)):
        data[CONF_USERNAME] = username
    if CONF_PASSWORD not in data and (password := data.pop("password", None)):
        data[CONF_PASSWORD] = password

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        minor_version=MIGRATION_MINOR_VERSION,
    )
    return True


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain services (one-time)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("services_registered"):
        return

    LOGGER.debug("Registering fitblocks_connect services")

    def _get_loaded_entry_or_raise(
        config_entry_id: str | None,
    ) -> FitblocksConnectConfigEntry:
        """Return a loaded config entry, optionally selected by ID."""
        if config_entry_id:
            entry = hass.config_entries.async_get_entry(config_entry_id)
            if entry is None or entry.domain != DOMAIN:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="config_entry_not_found",
                )
            if entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="config_entry_not_loaded",
                )
            return cast(FitblocksConnectConfigEntry, entry)

        loaded = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
        if not loaded:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_loaded_entries",
            )
        if len(loaded) > 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="multiple_entries_specify_id",
            )
        return cast(FitblocksConnectConfigEntry, loaded[0])

    def _get_runtime_data_or_raise(
        entry: FitblocksConnectConfigEntry,
    ) -> FitblocksConnectRuntimeData:
        """Return runtime data for a loaded entry."""
        if entry.runtime_data is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="config_entry_not_ready",
            )
        return cast(FitblocksConnectRuntimeData, entry.runtime_data)

    async def handle_enroll(call: ServiceCall) -> None:
        """Handle the fitblocks_connect.enroll service."""
        entry = _get_loaded_entry_or_raise(call.data.get(ATTR_CONFIG_ENTRY_ID))
        runtime_data = _get_runtime_data_or_raise(entry)
        client: FitblocksConnectClient = runtime_data.client
        coordinator: FitblocksConnectCoordinator = runtime_data.coordinator

        start = call.data["start"]
        end = call.data["end"]
        class_type_id = call.data["class_type_id"]

        if end <= start:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="end_time_after_start_time",
            )

        try:
            status = await client.async_enroll(
                start=start,
                end=end,
                class_type_id=class_type_id,
            )
            LOGGER.info("Enroll status: %s", status)
        except FitblocksConnectAuthError as err:
            LOGGER.debug("Service enroll authentication failed", exc_info=True)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="service_auth_failed",
            ) from err
        except FitblocksConnectError as err:
            LOGGER.debug("Service enroll failed", exc_info=True)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="service_call_failed",
            ) from err

        await coordinator.async_request_refresh()

    async def handle_unenroll(call: ServiceCall) -> None:
        """Handle the fitblocks_connect.unenroll service."""
        entry = _get_loaded_entry_or_raise(call.data.get(ATTR_CONFIG_ENTRY_ID))
        runtime_data = _get_runtime_data_or_raise(entry)
        client: FitblocksConnectClient = runtime_data.client
        coordinator: FitblocksConnectCoordinator = runtime_data.coordinator

        schedule_registration_id = call.data["schedule_registration_id"]
        class_type_id = call.data["class_type_id"]

        try:
            success = await client.async_unenroll(
                schedule_registration_id=schedule_registration_id,
                class_type_id=class_type_id,
            )
            LOGGER.info("Unenroll success=%s", success)
        except FitblocksConnectAuthError as err:
            LOGGER.debug("Service unenroll authentication failed", exc_info=True)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="service_auth_failed",
            ) from err
        except FitblocksConnectError as err:
            LOGGER.debug("Service unenroll failed", exc_info=True)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="service_call_failed",
            ) from err

        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        "enroll",
        handle_enroll,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
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
                vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
                vol.Required("schedule_registration_id"): cv.string,
                vol.Required("class_type_id"): cv.string,
            }
        ),
    )

    domain_data["services_registered"] = True


async def _async_reload_entry(
    hass: HomeAssistant, entry: FitblocksConnectConfigEntry
) -> None:
    """Reload the config entry after options changes."""

    await hass.config_entries.async_reload(entry.entry_id)
