"""Thermostat entity for the Caperplus heater."""

from __future__ import annotations

import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HOST,
    DOMAIN,
    FALLBACK_MAX_TEMP,
    FALLBACK_MIN_TEMP,
    MANUFACTURER,
    MODEL,
    TARGET_TEMP_STEP,
)
from .coordinator import CaperplusCoordinator
from .gizwits import GizwitsError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CaperplusCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CaperplusThermostat(coordinator, entry)])


class CaperplusThermostat(CoordinatorEntity[CaperplusCoordinator], ClimateEntity):
    """The heater's own thermostat: current water temp, setpoint, pause."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = TARGET_TEMP_STEP
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    def __init__(self, coordinator: CaperplusCoordinator, entry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        mac = entry.data.get("mac") or entry.data[CONF_HOST]
        self._attr_unique_id = f"{mac}_thermostat"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=entry.data.get("firmware"),
            configuration_url="https://api.gizwits.com",
        )

    # ------------------------------------------------------------ state
    @property
    def _state(self) -> dict:
        return self.coordinator.data or {}

    @property
    def native_current_temperature(self) -> float | None:
        value = self._state.get("temp")
        return round(value, 2) if isinstance(value, (int, float)) else None

    @property
    def native_target_temperature(self) -> float | None:
        value = self._state.get("temp_pid")
        return round(value, 2) if isinstance(value, (int, float)) else None

    @property
    def min_temp(self) -> float:
        """The device's own safety lower bound wins when it looks sane."""
        value = self._state.get("temp_min")
        if isinstance(value, (int, float)) and 15 <= value <= 30:
            return value
        return FALLBACK_MIN_TEMP

    @property
    def max_temp(self) -> float:
        value = self._state.get("temp_max")
        if isinstance(value, (int, float)) and 25 <= value <= 35:
            return value
        return FALLBACK_MAX_TEMP

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.OFF if self._state.get("paused") else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        if self._state.get("paused"):
            return HVACAction.OFF
        if self._state.get("water_out"):
            return HVACAction.IDLE
        return HVACAction.HEATING if self._state.get("heating") else HVACAction.IDLE

    @property
    def icon(self) -> str:
        return "mdi:fishbowl" if not self._state.get("heating") else "mdi:radiator"

    @property
    def extra_state_attributes(self) -> dict:
        state = self._state
        return {
            "加热中": state.get("heating"),
            "离水保护": state.get("water_out"),
            "当前功率_w": state.get("power_value"),
            "探头1_°c": state.get("temp1"),
            "探头2_°c": state.get("temp2"),
            "安全范围": f"{state.get('temp_min')}~{state.get('temp_max')} °C",
            "故障": ", ".join(state.get("faults") or []) or None,
            "运行小时": state.get("run_time"),
            "信号": state.get("rssi"),
            "固件": self._entry.data.get("firmware"),
        }

    # ------------------------------------------------------------ control
    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        temperature = max(self.min_temp, min(self.max_temp, float(temperature)))
        _LOGGER.debug("设置目标温度 %.2f °C", temperature)
        try:
            await self.coordinator.async_set_target_temperature(temperature)
        except GizwitsError as err:
            raise HomeAssistantError(f"设置温度失败：{err}") from err

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        try:
            await self.coordinator.async_set_paused(hvac_mode == HVACMode.OFF)
        except GizwitsError as err:
            raise HomeAssistantError(f"切换模式失败：{err}") from err
