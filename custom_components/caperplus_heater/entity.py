"""Shared entity base for the Caperplus heater."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN, MANUFACTURER, MODEL
from .coordinator import CaperplusCoordinator


class CaperplusEntity(CoordinatorEntity[CaperplusCoordinator]):
    """Base entity bound to the single heater device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CaperplusCoordinator, entry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        mac = entry.data.get("mac") or entry.data[CONF_HOST]
        self._attr_unique_id = f"{mac}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=entry.data.get("firmware"),
        )

    @property
    def _state(self) -> dict:
        return self.coordinator.data or {}
