"""Custom integration to integrate hass_nuki_bt with Home Assistant.

For more details about this integration, please refer to
https://github.com/ludeeus/hass_nuki_bt
"""

from __future__ import annotations
import logging
from asyncio import CancelledError, TimeoutError
from bleak import BleakError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_NAME, CONF_PIN
from homeassistant.core import HomeAssistant
from homeassistant.components import bluetooth
from homeassistant.exceptions import ConfigEntryNotReady


from pyNukiBT import NukiDevice, NukiConst

from .const import (
    CONF_APP_ID,
    CONF_AUTH_ID,
    CONF_DEVICE_ADDRESS,
    CONF_DEVICE_PUBLIC_KEY,
    CONF_PRIVATE_KEY,
    CONF_PUBLIC_KEY,
    CONF_CLIENT_TYPE,
    CONF_STATUS_RECONNECT,
    DEFAULT_STATUS_RECONNECT,
    DOMAIN,
)
from .coordinator import NukiDataUpdateCoordinator
from .status_reconnect import StatusReconnectNukiDevice

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.LOCK,
    Platform.SENSOR,
    Platform.BUTTON,
]

_LOGGER = logging.getLogger(__name__)


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up this integration using UI."""
    hass.data.setdefault(DOMAIN, {})
    address: str = entry.data[CONF_DEVICE_ADDRESS]

    if not bluetooth.async_address_present(hass, address, connectable=True):
        raise ConfigEntryNotReady(f"Could not find Nuki with address {address}")

    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if not ble_device:
        raise ConfigEntryNotReady(f"Could not find Nuki with address {address}")

    if entry.data.get(CONF_CLIENT_TYPE) == "App":
        client_type = NukiConst.NukiClientType.APP
    else:
        client_type = NukiConst.NukiClientType.BRIDGE

    device_class = (
        StatusReconnectNukiDevice
        if entry.options.get(CONF_STATUS_RECONNECT, DEFAULT_STATUS_RECONNECT)
        else NukiDevice
    )
    if device_class is StatusReconnectNukiDevice:
        _LOGGER.info("Nuki %s: status reconnect recovery enabled", entry.unique_id)
    device = device_class(
        address=entry.data[CONF_DEVICE_ADDRESS],
        auth_id=bytes.fromhex(entry.data[CONF_AUTH_ID]),
        nuki_public_key=bytes.fromhex(entry.data[CONF_DEVICE_PUBLIC_KEY]),
        bridge_public_key=bytes.fromhex(entry.data[CONF_PUBLIC_KEY]),
        bridge_private_key=bytes.fromhex(entry.data[CONF_PRIVATE_KEY]),
        app_id=int(entry.data[CONF_APP_ID]),
        client_type=client_type,
        name="HomeAssistant",
        ble_device=ble_device,
        get_ble_device=lambda addr: bluetooth.async_ble_device_from_address(
            hass, addr, connectable=True
        ),
    )
    try:
        await device.connect()
    except (BleakError, CancelledError, TimeoutError) as ex:
        _LOGGER.debug(ex)
        raise ConfigEntryNotReady(f"Could not connect to {address}")

    hass.data[DOMAIN][entry.entry_id] = coordinator = NukiDataUpdateCoordinator(
        hass=hass,
        logger=_LOGGER,
        ble_device=ble_device,
        device=device,
        base_unique_id=entry.unique_id,
        device_name=entry.data.get(CONF_NAME),
        connectable=True,
        security_pin=None if entry.data.get(CONF_PIN) is None else int(entry.data[CONF_PIN]),
    )

    if not await coordinator.async_wait_ready():
        raise ConfigEntryNotReady(f"{address} is not advertising state")

    entry.async_on_unload(coordinator.async_start())

    # entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    # await hass.config_entries.async_forward_entry_setups(
    #     entry, PLATFORMS_BY_TYPE[sensor_type]
    # )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    # await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        try:
            await coordinator.device.disconnect()
        except BleakError as ex:
            _LOGGER.debug("Nuki disconnect during unload failed: %s", type(ex).__name__)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
