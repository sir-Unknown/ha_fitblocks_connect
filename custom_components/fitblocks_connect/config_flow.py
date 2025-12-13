"""Config flow for the Fitblocks Connect custom component."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
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
from .models import FitblocksConnectConfigEntry


class FitblocksConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Fitblocks Connect."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize the Fitblocks Connect config flow."""
        self._errors: dict[str, str] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Step for manual configuration via the UI."""
        self._errors = {}

        if user_input is None:
            return self._show_user_form()

        base_url: str = str(user_input[CONF_BASE_URL]).rstrip("/")
        box: str = str(user_input[CONF_BOX]).strip("/")
        username: str = str(user_input[CONF_USERNAME]).strip()
        password: str = user_input[CONF_PASSWORD]
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

        self._async_abort_entries_match(
            {
                CONF_BASE_URL: base_url,
                CONF_BOX: box,
                CONF_USERNAME: username,
            }
        )

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
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
            },
            options={CONF_DISPLAY_NAME: display_name} if display_name else None,
        )

    async def async_step_reauth(self, _entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Perform reauth upon an authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm reauth and update stored credentials."""
        self._errors = {}

        reauth_entry = self._get_reauth_entry()
        data = reauth_entry.data

        if user_input is not None:
            username: str = str(
                user_input.get(CONF_USERNAME, data.get(CONF_USERNAME, ""))
            ).strip()
            password: str = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            client = FitblocksConnectClient(
                hass=self.hass,
                session=session,
                base_url=str(data[CONF_BASE_URL]),
                box=str(data[CONF_BOX]),
                username=username,
                password=password,
            )

            try:
                await client.async_login()
            except FitblocksConnectAuthError:
                self._errors["base"] = "invalid_auth"
            except FitblocksConnectError:
                self._errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, TimeoutError):
                LOGGER.exception("Network error during reauth")
                self._errors["base"] = "cannot_connect"

            if not self._errors:
                new_data = dict(data)
                new_data[CONF_USERNAME] = username
                new_data[CONF_PASSWORD] = password
                return self.async_update_reload_and_abort(reauth_entry, data=new_data)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_USERNAME,
                    default=str(data.get(CONF_USERNAME, "")),
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=self._errors,
        )

    @staticmethod
    def async_get_options_flow(
        _config_entry: FitblocksConnectConfigEntry,
    ) -> FitblocksConnectOptionsFlow:
        """Return the options flow handler."""

        return FitblocksConnectOptionsFlow()

    def _show_user_form(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show the configuration form."""
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
                    CONF_USERNAME,
                    default=user_input.get(CONF_USERNAME, ""),
                ): str,
                vol.Required(
                    CONF_PASSWORD,
                    default=user_input.get(CONF_PASSWORD, ""),
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


class FitblocksConnectOptionsFlow(OptionsFlow):
    """Options flow to update the Fitblocks Connect display name."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the Fitblocks Connect options."""

        if user_input is not None:
            display_name = user_input.get(CONF_DISPLAY_NAME, "").strip()
            new_options = dict(self.config_entry.options)
            if display_name:
                new_options[CONF_DISPLAY_NAME] = display_name
            else:
                new_options.pop(CONF_DISPLAY_NAME, None)
            return self.async_create_entry(title="", data=new_options)

        current_display_name: str = self.config_entry.options.get(
            CONF_DISPLAY_NAME
        ) or self.config_entry.data.get(CONF_DISPLAY_NAME, "")

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DISPLAY_NAME,
                    default=current_display_name,
                ): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )
