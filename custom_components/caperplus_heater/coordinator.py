"""Data coordinator: polls the heater over the LAN."""

from __future__ import annotations

import functools
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .gizwits import DeviceBusy, GizwitsError, GizwitsLocal, discover

_LOGGER = logging.getLogger(__name__)

FAILURES_BEFORE_UNAVAILABLE = 3


class CaperplusCoordinator(DataUpdateCoordinator[dict]):
    """Reads the full 48-byte state in one round trip, every scan interval."""

    def __init__(self, hass: HomeAssistant, host: str, expected_mac: str | None = None) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.host = host
        self.expected_mac = expected_mac
        self._consecutive_failures = 0

    # ---------------------------------------------------------------- polling
    async def _async_update_data(self) -> dict:
        try:
            state = await self.hass.async_add_executor_job(self._read_once)
        except DeviceBusy as err:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 2:
                # IP may have moved (DHCP): try to find it again by MAC
                try:
                    await self.async_rediscover()
                except Exception:  # noqa: BLE001 - discovery is best effort
                    _LOGGER.debug("重新发现失败", exc_info=True)
            if self._consecutive_failures >= FAILURES_BEFORE_UNAVAILABLE:
                raise UpdateFailed(f"设备无响应（鱼乐世界 App 可能正占用设备）：{err}") from err
            _LOGGER.debug("瞬时读取失败 %d 次：%s", self._consecutive_failures, err)
            if self.data:
                return self.data
            raise UpdateFailed(str(err)) from err
        except GizwitsError as err:
            self._consecutive_failures += 1
            raise UpdateFailed(str(err)) from err
        self._consecutive_failures = 0
        return state

    def _read_once(self) -> dict:
        with GizwitsLocal(self.host) as device:
            return device.read_state()

    def _write_once(self, values: dict) -> dict:
        with GizwitsLocal(self.host) as device:
            return device.write(**values)

    # ---------------------------------------------------------------- control
    async def async_write(self, **values) -> None:
        state = await self.hass.async_add_executor_job(functools.partial(self._write_once, values))
        self.async_set_updated_data(state)

    async def async_set_target_temperature(self, temperature: float) -> None:
        await self.async_write(temp_pid=temperature)

    async def async_set_paused(self, paused: bool) -> None:
        """dev_config bit0: 1 = 强制暂停加热."""
        current = self.data or {}
        config = int(current.get("dev_config", 0))
        config = (config | 0x01) if paused else (config & ~0x01)
        await self.async_write(dev_config=config)

    async def async_rediscover(self) -> bool:
        """Re-find the device after a DHCP lease change."""
        devices = await self.hass.async_add_executor_job(discover)
        for dev in devices:
            if dev.get("mac") and dev["mac"] == self.expected_mac:
                if dev["ip"] != self.host:
                    _LOGGER.info("设备 IP 变更：%s → %s", self.host, dev["ip"])
                    self.host = dev["ip"]
                return True
        return False
