"""Config flow for the Caperplus heater."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME

from .const import DOMAIN, MODEL, PRODUCT_KEY
from .gizwits import DeviceBusy, GizwitsError, GizwitsLocal, discover

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_HOST, default=""): str,
        vol.Optional(CONF_NAME, default="鱼缸加热棒"): str,
    }
)


class CaperplusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for an IP (or discover one) and verify the device answers."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input.get(CONF_HOST) or "").strip()
            name = str(user_input.get(CONF_NAME) or MODEL).strip()
            try:
                info = await self.hass.async_add_executor_job(self._probe, host)
            except GizwitsError as err:
                _LOGGER.debug("发现到多台设备：%s", err)
                errors["base"] = "multiple_devices"
            except DeviceBusy as err:
                _LOGGER.debug("连接失败：%s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("配置时发生意外错误")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info.get("mac") or info["ip"])
                self._abort_if_unique_id_configured(updates={CONF_HOST: info["ip"]})
                return self.async_create_entry(
                    title=name or MODEL,
                    data={
                        CONF_HOST: info["ip"],
                        CONF_NAME: name or MODEL,
                        "mac": info.get("mac"),
                        "firmware": info.get("firmware"),
                        "product_key": info.get("product_key", PRODUCT_KEY),
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    def _probe(host: str) -> dict:
        """Verify the device: broadcast discovery first, then a read attempt."""
        if not host:
            devices = discover()
            if not devices:
                raise DeviceBusy("没有发现设备，请填写 IP")
            if len(devices) > 1:
                raise GizwitsError("发现多台设备")
            host = devices[0]["ip"]

        info = {"ip": host}
        for dev in discover():
            if dev["ip"] == host:
                info = dev
                break

        with GizwitsLocal(host) as device:
            device.read_raw()  # raises if the device is not really usable
        return info
