"""Binary sensors for the Caperplus heater."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CaperplusCoordinator
from .entity import CaperplusEntity


@dataclass(frozen=True, kw_only=True)
class CaperplusBinarySensor(BinarySensorEntityDescription):
    """Binary sensor description bound to a decoded datapoint."""

    field: str


BINARY_SENSORS: tuple[CaperplusBinarySensor, ...] = (
    CaperplusBinarySensor(
        key="heating",
        translation_key="heating",
        field="heating",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:radiator",
    ),
    CaperplusBinarySensor(
        key="water_out",
        translation_key="water_out",
        field="water_out",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:water-off",
    ),
    CaperplusBinarySensor(
        key="fault",
        translation_key="fault",
        field="any_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:alert-circle-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CaperplusCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CaperplusBinarySensorEntity(coordinator, entry, desc) for desc in BINARY_SENSORS
    )


class CaperplusBinarySensorEntity(CaperplusEntity, BinarySensorEntity):
    """State flag plus a readable fault list."""

    entity_description: CaperplusBinarySensor

    def __init__(
        self, coordinator: CaperplusCoordinator, entry, description: CaperplusBinarySensor
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self._state.get(self.entity_description.field)
        return bool(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.key != "fault":
            return None
        state = self._state
        return {
            "故障明细": state.get("faults") or [],
            "fault_temp": state.get("fault_temp"),
            "fault_heater": state.get("fault_heater"),
            "fault_power": state.get("fault_power"),
            "fault_zero": state.get("fault_zero"),
        }
