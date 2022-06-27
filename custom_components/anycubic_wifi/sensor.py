"""Platform for sensor integration."""
from __future__ import annotations
import asyncio
from datetime import timedelta
import datetime
from typing import Any
import logging

from uart_wifi.response import MonoXStatus
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_UNIQUE_ID
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from uart_wifi.errors import AnycubicException
from .api import MonoXAPI
from .base_entry import AnycubicUartEntityBase
from .const import (
    CONF_MODEL,
    CONF_SERIAL,
    DOMAIN,
    PRINTER_ICON,
    UART_WIFI_PORT,
    POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)
_ATTR_FILE = "file"
_ATTR_PRINTVOL = "print_vol_mL"
_ATTR_CURLAYER = "current_layer_num"
_ATTR_TOTALLAYER = "total_layer_num"
_ATTR_REMLAYER = "remaining_layer_num"
_ATTR_ELAPSEDTIME = "elapsed_time"
_ATTR_REMAINTIME = "remaining_time"

SCAN_INTERVAL = timedelta(seconds=POLL_INTERVAL)


async def async_setup(entry: config_entries.ConfigEntry, ) -> None:
    """The setup method"""
    _LOGGER.debug(entry)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the platform from config_entry."""
    if entry.unique_id not in hass.data[DOMAIN]:
        hass.data[DOMAIN][entry.unique_id] = DOMAIN + entry[CONF_SERIAL]

    @callback
    async def async_add_sensor() -> None:
        """Add binary sensor from Anycubic device."""

        the_sensor = MonoXSensor(hass, entry)
        async_add_entities([the_sensor])
        entry.async_on_unload(
            entry.add_update_listener(the_sensor.async_update))

    await async_add_sensor()


class MonoXSensor(SensorEntity, AnycubicUartEntityBase, RestoreEntity):
    """A simple sensor."""

    # _attr_changed_by = None
    _attr_icon = PRINTER_ICON
    _attr_device_class = "3D Printer"
    should_poll = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(entry)
        self.cancel_scheduled_update = None
        self.entry = entry
        self.hass = hass

        if not self.name:
            self._attr_name = entry.data[CONF_MODEL]

        if not self.unique_id:
            self._attr_unique_id = entry.entry_id
            entry.data[CONF_UNIQUE_ID] = entry.entry_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN,
                                                          entry.unique_id)})

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            response: MonoXStatus = await asyncio.wait_for(
                MonoXAPI(self.entry.data[CONF_HOST],
                         UART_WIFI_PORT).getstatus(), 10)
        except AnycubicException:
            return
        if response is None or not isinstance(response, MonoXStatus):
            return
        self._attr_extra_state_attributes = {}

        if response is not None:
            if hasattr(response, "status"):
                self._attr_native_value = response.status.strip()
                self._attr_state = self._attr_native_value.strip()
            else:
                return
            if hasattr(response, "current_layer"):
                self.set_attr_int(_ATTR_CURLAYER, int(response.current_layer))
            if hasattr(response, "total_layers"):
                self.set_attr_int(_ATTR_TOTALLAYER, int(response.total_layers))
            if hasattr(response, "current_layer") and hasattr(
                    response, "total_layers"):
                self.set_attr_int(
                    _ATTR_REMLAYER,
                    int(
                        int(response.total_layers) -
                        int(response.current_layer)),
                )
            if hasattr(response, "seconds_elapse"):
                self.set_attr_time(_ATTR_ELAPSEDTIME,
                                   int(response.seconds_elapse))
            if hasattr(response, "seconds_remaining"):
                self.set_attr_time(_ATTR_REMAINTIME,
                                   int(response.seconds_remaining))
            if hasattr(response, "file"):
                self._attr_extra_state_attributes[
                    _ATTR_FILE] = response.file.split("/", 1)
            if hasattr(response, "total_volume"):
                self.set_attr_int(
                    _ATTR_PRINTVOL,
                    float(
                        response.total_volume.replace("~", "",
                                                      1).replace("mL", "", 1)),
                )

        self.hass.states.async_set(
            entity_id=self.entity_id,
            new_state=self._attr_state,
            attributes=self._attr_extra_state_attributes,
            force_update=self.force_update,
            context=self._context,
        )

    async def async_added_to_hass(self):
        """Lifecycle Method when the device is added to HASS"""
        last_state = await self.async_get_last_state()
        self._attr_state = last_state.state
        self._attr_native_value = last_state.state
        last_extras = await self.async_get_last_extra_data()
        self._attr_extra_state_attributes = last_extras

    def set_attr_int(self, key: str, value: int) -> None:
        """Handle state attributes"""
        self._attr_extra_state_attributes[key] = int(value)

    def set_attr_time(self, key: str, value: int) -> None:
        """Handle state attributes"""
        self._attr_extra_state_attributes[key] = str(
            datetime.timedelta(seconds=value))

    @callback
    def update_callback(self, no_delay=False) -> None:  # pylint: disable=unused-argument
        """Update the sensor's state, if needed.

        Parameter no_delay is True when device_event_reachable is sent.
        """
        self.hass.add_job(self.async_update_ha_state(self.async_update))

        @callback
        def scheduled_update(now):  # pylint: disable=unused-argument
            """Timer callback for sensor update."""
            self.cancel_scheduled_update = None

    @callback
    def async_check_significant_change(
            self,  # pylint: disable=unused-argument
            hass: HomeAssistant,  # pylint: disable=unused-argument
            old_state: str,
            old_attrs: dict,  # pylint: disable=unused-argument
            new_state: str,
            new_attrs: dict,  # pylint: disable=unused-argument
            **kwargs: Any,  # pylint: disable=unused-argument
    ) -> bool:
        """Significant Change Support. Insignificant changes are attributes only."""
        if old_state != new_state:
            return True
        return False
