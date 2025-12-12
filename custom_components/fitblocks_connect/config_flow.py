"""Config flow for the Fitblocks Connect custom component."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import (
    FitblocksConnectAuthError,
    FitblocksConnectClient,
    FitblocksConnectError,
)
from .const import (
    CONF_BASE_URL,
    CONF_BOX,
    CONF_DISPLAY_NAME,
    DEFAULT_BASE_URL,
    DEFAULT_BOX,
    DOMAIN,
    LOGGER,
)


class FitblocksConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow voor Fitblocks Connect."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the Fitblocks Connect config flow."""
        self._errors: dict[str, str] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Stap voor handmatige configuratie via de UI."""
        self._errors = {}

        if user_input is None:
            return self._show_user_form()

        base_url: str = user_input[CONF_BASE_URL]
        box: str = user_input[CONF_BOX]
        username: str = user_input["username"]
        password: str = user_input["password"]
        display_name_in: str = user_input.get(CONF_DISPLAY_NAME, "").strip()

        session = async_get_clientsession(self.hass)
        client = FitblocksConnectClient(
            hass=self.hass,
            session=session,
            base_url=base_url,
            box=box,
            username=username,
            password=password,
        )

        branding_name: str | None = None

        try:
            await client.async_login()

            try:
                branding_result = await client.async_fetch_branding()
            except AttributeError:
                branding_result = None

            if isinstance(branding_result, (tuple, list)):
                if branding_result:
                    branding_name = branding_result[0]
            elif isinstance(branding_result, str) or branding_result is None:
                branding_name = branding_result

        except FitblocksConnectAuthError:
            self._errors["base"] = "invalid_auth"
        except FitblocksConnectError:
            self._errors["base"] = "cannot_connect"
        except (aiohttp.ClientError, TimeoutError):
            LOGGER.exception("Network error during config flow login/branding")
            self._errors["base"] = "cannot_connect"

        if self._errors:
            return self._show_user_form(user_input)

        if branding_name:
            title = branding_name
        else:
            title = f"{box} @ {base_url}"

        if display_name_in:
            display_name = display_name_in
        else:
            user_part = username.split("@", 1)[0]
            display_name = (
                user_part.replace(".", " ").replace("_", " ").title()
                if user_part
                else username
            )

        return self.async_create_entry(
            title=title,
            data={
                CONF_BASE_URL: base_url,
                CONF_BOX: box,
                "username": username,
                "password": password,
                CONF_DISPLAY_NAME: display_name,
            },
        )

    def is_matching(self, other_flow: ConfigFlow) -> bool:
        """Return True if other_flow describes the same setup attempt."""
        return False

    def _show_user_form(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Config formulier tonen."""
        user_input = user_input or {}

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_BASE_URL,
                    default=user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                ): str,
                vol.Required(
                    CONF_BOX,
                    default=user_input.get(CONF_BOX, DEFAULT_BOX),
                ): str,
                vol.Required(
                    "username",
                    default=user_input.get("username", ""),
                ): str,
                vol.Required(
                    "password",
                    default=user_input.get("password", ""),
                ): str,
                vol.Optional(
                    CONF_DISPLAY_NAME,
                    default=user_input.get(CONF_DISPLAY_NAME, ""),
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=self._errors,
        )
