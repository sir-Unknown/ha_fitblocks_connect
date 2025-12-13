"""Client for interacting with the Fitblocks Connect backend."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
import html as html_module
import re
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import LOGGER, REQUEST_TIMEOUT

CSRF_META_RE = re.compile(
    r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

HEADER_TITLE_RE = re.compile(
    r'<span[^>]*class=["\']header-visual-title["\'][^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)

# Match both "BAR 'S" and "BAR'S" after .title():
APOS_FIX_RE = re.compile(r"\s*'S\b", re.IGNORECASE)


class FitblocksConnectError(Exception):
    """Base exception for Fitblocks Connect errors."""


class FitblocksConnectAuthError(FitblocksConnectError):
    """Raised when authentication fails."""


class FitblocksConnectConnectionError(FitblocksConnectError):
    """Raised when communication with the server fails."""


class FitblocksConnectSSLError(FitblocksConnectConnectionError):
    """Raised when SSL certificate verification fails."""


class FitblocksConnectApiError(FitblocksConnectError):
    """Raised when the API returns an error."""


@dataclass
class FitblocksConnectConfig:
    """Configuration for FitblocksConnectClient."""

    base_url: str
    box: str
    username: str
    password: str


class FitblocksConnectClient:
    """HTTP client for FitBlocks / Fitblocks Connect."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        base_url: str,
        box: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client."""
        self._hass = hass
        self._session = session
        self._config = FitblocksConnectConfig(
            base_url=base_url.rstrip("/"),
            box=box.strip("/"),
            username=username,
            password=password,
        )
        self._csrf_token: str | None = None
        self._logged_in: bool = False

        # Store the gym name branding only
        self._branding_name: str | None = None

    @staticmethod
    def _format_event_datetime(value: datetime) -> str:
        """Format datetimes in the format expected by Fitblocks endpoints.

        Some endpoints (such as `classTypeDetails`) expect local time without a
        timezone suffix, for example: `2025-12-16T18:45:00`.
        """
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        local = dt_util.as_local(value)
        return local.replace(tzinfo=None).isoformat(timespec="seconds")

    # ---------- properties ----------

    @property
    def csrf_token(self) -> str | None:
        """Return the current CSRF token (for debugging)."""
        return self._csrf_token

    @property
    def branding_name(self) -> str | None:
        r"""Normalized gym name, for example "Bar's Gym"."""
        return self._branding_name

    @property
    def user_email(self) -> str:
        """Email address of the logged-in user (from config)."""
        return self._config.username

    @property
    def base_url(self) -> str:
        """Configured base URL without trailing slash."""
        return self._config.base_url

    @property
    def box(self) -> str:
        """Configured Fitblocks box slug."""
        return self._config.box

    @property
    def is_logged_in(self) -> bool:
        """Return if the client completed the login flow."""
        return self._logged_in

    # ---------- helpers ----------

    def _build_url(self, endpoint: str) -> str:
        """Build a URL like https://fitblocks.nl/physicsperformance/<endpoint>."""
        endpoint = endpoint.lstrip("/")
        return f"{self._config.base_url}/{self._config.box}/{endpoint}"

    @asynccontextmanager
    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        """Perform an HTTP request with consistent error handling."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(method, url, **kwargs) as resp:
                    yield resp
        except aiohttp.ClientConnectorCertificateError as err:
            raise FitblocksConnectSSLError(
                "SSL certificate verification failed"
            ) from err
        except aiohttp.ClientSSLError as err:
            raise FitblocksConnectSSLError("SSL error") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise FitblocksConnectConnectionError(
                "Error communicating with the server"
            ) from err

    async def async_login(self) -> None:
        """Perform login flow and store CSRF token and cookies."""
        login_url = self._build_url("login")

        LOGGER.debug("FitblocksConnect: GET login page %s", login_url)
        async with self._request("GET", login_url) as resp:
            if resp.status != 200:
                LOGGER.debug("Login page returned status=%s", resp.status)
                raise FitblocksConnectError(
                    f"Unexpected status for login page: {resp.status}"
                )
            html = await resp.text()
        csrf = self._extract_csrf_token(html)
        if not csrf:
            raise FitblocksConnectError("CSRF token not found on login page")

        self._csrf_token = csrf

        form_data = {
            "_token": csrf,
            "email": self._config.username,
            "password": self._config.password,
            "remember": "1",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        LOGGER.debug("FitblocksConnect: POST login")
        async with self._request(
            "POST",
            login_url,
            data=form_data,
            headers=headers,
        ) as post_resp:
            if post_resp.status not in (200, 302):
                LOGGER.debug("Login failed status=%s", post_resp.status)
                if post_resp.status in (401, 403):
                    raise FitblocksConnectAuthError("Invalid credentials")
                raise FitblocksConnectError(
                    f"Login failed with status {post_resp.status}"
                )

        try:
            await self._async_refresh_csrf_from_schedule()
        except FitblocksConnectError:
            LOGGER.debug("Could not refresh CSRF from schedule page", exc_info=True)

        self._logged_in = True
        LOGGER.debug("FitblocksConnect: login successful")

    async def _async_refresh_csrf_from_schedule(self) -> None:
        """GET /{box}/schedule and refresh the CSRF token if present."""
        schedule_url = self._build_url("schedule")
        LOGGER.debug(
            "FitblocksConnect: GET schedule page %s for CSRF refresh", schedule_url
        )
        async with self._request("GET", schedule_url) as resp:
            if resp.status != 200:
                LOGGER.debug(
                    "Schedule page status=%s; keeping existing CSRF",
                    resp.status,
                )
                return
            html = await resp.text()
        csrf = self._extract_csrf_token(html)
        if csrf:
            self._csrf_token = csrf
            LOGGER.debug("FitblocksConnect: refreshed CSRF token from schedule page")

    @staticmethod
    def _extract_csrf_token(html: str) -> str | None:
        """Extract CSRF token from meta-tag."""
        match = CSRF_META_RE.search(html)
        if not match:
            return None
        return match.group(1)

    async def _ensure_logged_in(self) -> None:
        """Ensure we are logged in before making API calls."""
        if self._logged_in and self._csrf_token:
            return
        await self.async_login()

    def _ensure_csrf_header(self) -> dict[str, str]:
        """Return headers with X-CSRF-TOKEN and X-Requested-With."""
        if not self._csrf_token:
            raise FitblocksConnectError("CSRF token not available")
        return {
            "X-CSRF-TOKEN": self._csrf_token,
            "X-Requested-With": "XMLHttpRequest",
        }

    @staticmethod
    def _format_iso8601_z(dt: datetime) -> str:
        """ISO8601 with Z suffix (UTC)."""
        iso = dt_util.as_utc(dt).isoformat(timespec="milliseconds")
        return iso.replace("+00:00", "Z")

    # ---------- API calls ----------

    async def async_get_schedule(
        self,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """Fetch the schedule via /{box}/schedule/json."""
        await self._ensure_logged_in()

        url = self._build_url("schedule/json")
        params = {
            "start": self._format_iso8601_z(start),
            "end": self._format_iso8601_z(end),
        }
        headers = self._ensure_csrf_header()

        LOGGER.debug("FitblocksConnect: GET schedule/json %s params=%s", url, params)

        async with self._request(
            "GET",
            url,
            params=params,
            headers=headers,
        ) as resp:
            if resp.status == 401:
                raise FitblocksConnectAuthError("Unauthorized while fetching schedule")
            if resp.status != 200:
                LOGGER.debug("Schedule request failed status=%s", resp.status)
                raise FitblocksConnectApiError(
                    f"Unexpected status from schedule/json: {resp.status}"
                )
            data: dict[str, Any] = await resp.json()
            return data

    async def async_get_class_type_details(
        self,
        class_type_id: str,
        event_id: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """Fetch details for a lesson/event via /{box}/classTypeDetails."""
        await self._ensure_logged_in()

        url = self._build_url("classTypeDetails")
        params = {
            "classTypeId": class_type_id,
            "eventId": event_id,
            "eventDate": self._format_event_datetime(start),
            "eventEndDate": self._format_event_datetime(end),
        }
        headers = self._ensure_csrf_header()

        LOGGER.debug("FitblocksConnect: GET classTypeDetails %s params=%s", url, params)

        async with self._request(
            "GET",
            url,
            params=params,
            headers=headers,
        ) as resp:
            if resp.status == 401:
                raise FitblocksConnectAuthError(
                    "Unauthorized while fetching classTypeDetails"
                )
            if resp.status != 200:
                LOGGER.debug("classTypeDetails request failed status=%s", resp.status)
                raise FitblocksConnectApiError(
                    f"Unexpected status from classTypeDetails: {resp.status}"
                )
            data: dict[str, Any] = await resp.json()
            return data

    async def async_enroll(
        self,
        start: datetime,
        end: datetime,
        class_type_id: str,
    ) -> str:
        """Enroll in a lesson (subscribeToScheduleItem)."""
        await self._ensure_logged_in()

        url = self._build_url("subscribeToScheduleItem")
        headers = self._ensure_csrf_header()
        headers.update({"Content-Type": "application/json;charset=UTF-8"})

        payload = {
            "startDate": self._format_event_datetime(start),
            "endDate": self._format_event_datetime(end),
            "classTypeId": class_type_id,
        }

        LOGGER.debug("FitblocksConnect: POST enroll %s", url)

        async with self._request(
            "POST",
            url,
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status == 401:
                raise FitblocksConnectAuthError("Unauthorized while enrolling")

            if resp.status != 200:
                LOGGER.debug("Enroll request failed status=%s", resp.status)
                raise FitblocksConnectApiError(
                    f"Unexpected status from subscribeToScheduleItem: {resp.status}"
                )

            result: Any = await resp.json(content_type=None)
            if isinstance(result, dict) and (status := result.get("status")):
                return str(status)
            # Some environments do not return an explicit status; HTTP 200 is sufficient
            return "success"

    async def async_unenroll(
        self,
        schedule_registration_id: str,
        class_type_id: str,
    ) -> bool:
        """Unenroll from a lesson (unsubscribeFromScheduleItem)."""
        await self._ensure_logged_in()

        url = self._build_url("unsubscribeFromScheduleItem")
        headers = self._ensure_csrf_header()
        headers.update({"Content-Type": "application/json;charset=UTF-8"})

        payload = {
            "scheduleRegistrationId": schedule_registration_id,
            "classTypeId": class_type_id,
        }

        LOGGER.debug("FitblocksConnect: POST unenroll %s", url)

        async with self._request(
            "POST",
            url,
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status == 401:
                raise FitblocksConnectAuthError("Unauthorized while unenrolling")

            if resp.status != 200:
                LOGGER.debug("Unenroll request failed status=%s", resp.status)
                raise FitblocksConnectApiError(
                    f"Unexpected status from unsubscribeFromScheduleItem: {resp.status}"
                )

            await resp.json(content_type=None)
            # The API uses only the HTTP status as the success indicator
            return True

    async def async_get_membership(self) -> dict[str, Any]:
        """Stub for the membership/credits API (not implemented yet)."""
        raise NotImplementedError("Membership API not implemented yet")

    # ---------- Branding helpers (name only) ----------

    def _normalize_brand_name(self, raw: str) -> str:
        """Normalize gym name, for example BAR'S GYM / BAR 'S GYM -> Bar's Gym."""
        if not raw:
            return ""

        text = html_module.unescape(raw).strip()
        text = re.sub(r"\s+", " ", text)

        lower = text.lower()
        titled = lower.title()  # "Bar'S Gym" / "Bar 'S Gym"

        # Fix both " 'S" and "'S" to "'s"
        return APOS_FIX_RE.sub("'s", titled)

    def _extract_brand_name(self, html: str) -> str | None:
        """Extract only the title name from the HTML."""
        m = HEADER_TITLE_RE.search(html)
        if not m:
            return None
        raw_title = m.group(1)
        return self._normalize_brand_name(raw_title)

    async def async_fetch_branding(self) -> str | None:
        """Load the dashboard page and extract the branding name."""
        url = self._build_url("")  # /{box}/
        LOGGER.debug("FitblocksConnect: GET branding page %s", url)

        async with self._request("GET", url) as resp:
            if resp.status != 200:
                LOGGER.debug("Branding page status=%s", resp.status)
                return None
            html = await resp.text()
        name = self._extract_brand_name(html)

        self._branding_name = name
        LOGGER.debug("Branding: name=%s", name)

        return name
