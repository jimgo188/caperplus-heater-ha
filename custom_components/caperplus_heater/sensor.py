"""Sensors for the Caperplus heater."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CaperplusCoordinator
from .entity import CaperplusEntity


@dataclass(frozen=True, kw_only=True)
class CaperplusSensor(SensorEntityDescription):
    """Sensor description bound to a decoded datapoint."""

    field: str
    scale: float = 1.0


SENSORS: tuple[CaperplusSensor, ...] = (
    CaperplusSensor(
        key="water_temperature",
        translation_key="water_temperature",
        field="temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:coolant-temperature",
    ),
    CaperplusSensor(
        key="power",
        translation_key="power",
        field="power_value",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:flash",
    ),
    CaperplusSensor(
        key="probe1",
        translation_key="probe1",
        field="temp1",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    CaperplusSensor(
        key="probe2",
        translation_key="probe2",
        field="temp2",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    CaperplusSensor(
        key="signal",
        translation_key="signal",
        field="rssi",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:wifi",
    ),
    CaperplusSensor(
        key="run_time",
        translation_key="run_time",
        field="run_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:timer-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CaperplusCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CaperplusSensorEntity(coordinator, entry, desc) for desc in SENSORS)


class CaperplusSensorEntity(CaperplusEntity, SensorEntity):
    """One decoded datapoint as a sensor."""

    entity_description: CaperplusSensor

    def __init__(self, coordinator: CaperplusCoordinator, entry, description: CaperplusSensor) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        value = self._state.get(self.entity_description.field)
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return round(value * self.entity_description.scale, 2)
        return value
