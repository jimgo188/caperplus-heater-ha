"""Caperplus (光特亿 鱼乐世界) WiFi heater — local Gizwits GAgent integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, DOMAIN, PLATFORMS
from .coordinator import CaperplusCoordinator

PLATFORM_LIST = [Platform(platform) for platform in PLATFORMS]

__all__ = ["async_setup_entry", "async_unload_entry", "CaperplusConfigEntry"]

type CaperplusConfigEntry = ConfigEntry[CaperplusCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: CaperplusConfigEntry) -> bool:
    """Set up the heater from a config entry."""
    coordinator = CaperplusCoordinator(hass, entry.data[CONF_HOST], entry.data.get("mac"))
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORM_LIST)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CaperplusConfigEntry) -> bool:
    """Unload the config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORM_LIST)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
