"""Platform for Whirlpool sensors (washer/dryer and now aircon)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from whirlpool.aircon import Aircon
from whirlpool.washerdryer import MachineState, WasherDryer

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util.dt import utcnow

from . import WhirlpoolConfigEntry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# -----------------------------------------------------------------------------------
# Washer/Dryer Sensors (unchanged from official code, except reorganized for clarity)
# -----------------------------------------------------------------------------------

TANK_FILL = {
    "0": "unknown",
    "1": "empty",
    "2": "25",
    "3": "50",
    "4": "100",
    "5": "active",
}

MACHINE_STATE = {
    MachineState.Standby: "standby",
    MachineState.Setting: "setting",
    MachineState.DelayCountdownMode: "delay_countdown",
    MachineState.DelayPause: "delay_paused",
    MachineState.SmartDelay: "smart_delay",
    MachineState.SmartGridPause: "smart_grid_pause",
    MachineState.Pause: "pause",
    MachineState.RunningMainCycle: "running_maincycle",
    MachineState.RunningPostCycle: "running_postcycle",
    MachineState.Exceptions: "exception",
    MachineState.Complete: "complete",
    MachineState.PowerFailure: "power_failure",
    MachineState.ServiceDiagnostic: "service_diagnostic_mode",
    MachineState.FactoryDiagnostic: "factory_diagnostic_mode",
    MachineState.LifeTest: "life_test",
    MachineState.CustomerFocusMode: "customer_focus_mode",
    MachineState.DemoMode: "demo_mode",
    MachineState.HardStopOrError: "hard_stop_or_error",
    MachineState.SystemInit: "system_initialize",
}

def washer_state(washer: WasherDryer) -> str | None:
    """Determine correct states for a washer/dryer."""
    DOOR_OPEN = "door_open"

    if washer.get_attribute("Cavity_OpStatusDoorOpen") == "1":
        return DOOR_OPEN

    machine_state = washer.get_machine_state()

    CYCLE_FUNC = [
        (WasherDryer.get_cycle_status_filling, "cycle_filling"),
        (WasherDryer.get_cycle_status_rinsing, "cycle_rinsing"),
        (WasherDryer.get_cycle_status_sensing, "cycle_sensing"),
        (WasherDryer.get_cycle_status_soaking, "cycle_soaking"),
        (WasherDryer.get_cycle_status_spinning, "cycle_spinning"),
        (WasherDryer.get_cycle_status_washing, "cycle_washing"),
    ]

    if machine_state == MachineState.RunningMainCycle:
        for func, cycle_name in CYCLE_FUNC:
            if func(washer):
                return cycle_name

    return MACHINE_STATE.get(machine_state)


@dataclass(frozen=True, kw_only=True)
class WhirlpoolSensorEntityDescription(SensorEntityDescription):
    """Describes Whirlpool Washer/Dryer sensor entity."""
    value_fn: Callable


SENSORS: tuple[WhirlpoolSensorEntityDescription, ...] = (
    WhirlpoolSensorEntityDescription(
        key="state",
        translation_key="whirlpool_machine",
        device_class=SensorDeviceClass.ENUM,
        options=(
            list(MACHINE_STATE.values())
            + ["cycle_filling", "cycle_rinsing", "cycle_sensing", "cycle_soaking",
               "cycle_spinning", "cycle_washing", "door_open"]
        ),
        value_fn=washer_state,
    ),
    WhirlpoolSensorEntityDescription(
        key="DispenseLevel",
        translation_key="whirlpool_tank",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.ENUM,
        options=list(TANK_FILL.values()),
        value_fn=lambda wd: TANK_FILL.get(
            wd.get_attribute("WashCavity_OpStatusBulkDispense1Level")
        ),
    ),
)

# Washer/dryer time sensor
SENSOR_TIMER: tuple[SensorEntityDescription] = (
    SensorEntityDescription(
        key="timeremaining",
        translation_key="end_time",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


class WasherDryerClass(SensorEntity):
    """A sensor entity for Whirlpool washers/dryers."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        washer_dryer: WasherDryer,
        description: WhirlpoolSensorEntityDescription
    ) -> None:
        """Initialize the washer sensor."""
        self._wd: WasherDryer = washer_dryer
        self.entity_description = description

        # Icon
        if washer_dryer.name == "dryer":
            self._attr_icon = "mdi:tumble-dryer"
        else:
            self._attr_icon = "mdi:washing-machine"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, washer_dryer.said)},
            name=washer_dryer.name.capitalize(),
            manufacturer="Whirlpool",
        )
        self._attr_unique_id = f"{washer_dryer.said}-{description.key}"

    async def async_added_to_hass(self) -> None:
        """Register updates callback."""
        self._wd.register_attr_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister updates callback."""
        self._wd.unregister_attr_callback(self.async_write_ha_state)

    @property
    def available(self) -> bool:
        """Return True if online."""
        return self._wd.get_online()

    @property
    def native_value(self) -> StateType | str:
        """Return the sensor value."""
        return self.entity_description.value_fn(self._wd)


class WasherDryerTimeClass(RestoreSensor):
    """A timestamp sensor for Whirlpool washers/dryers (cycle end time)."""

    _attr_should_poll = True
    _attr_has_entity_name = True

    def __init__(self, washer_dryer: WasherDryer, description: SensorEntityDescription) -> None:
        """Initialize the washer time sensor."""
        self._wd: WasherDryer = washer_dryer
        self.entity_description = description
        self._running: bool | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, washer_dryer.said)},
            name=washer_dryer.name.capitalize(),
            manufacturer="Whirlpool",
        )
        self._attr_unique_id = f"{washer_dryer.said}-{description.key}"

        if washer_dryer.name == "dryer":
            self._attr_icon = "mdi:tumble-dryer"
        else:
            self._attr_icon = "mdi:washing-machine"

    async def async_added_to_hass(self) -> None:
        """Restore sensor data and register callback."""
        if restored_data := await self.async_get_last_sensor_data():
            self._attr_native_value = restored_data.native_value
        await super().async_added_to_hass()
        self._wd.register_attr_callback(self.update_from_latest_data)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback."""
        self._wd.unregister_attr_callback(self.update_from_latest_data)

    @property
    def available(self) -> bool:
        """Return True if online."""
        return self._wd.get_online()

    async def async_update(self) -> None:
        """Fetch updated data from the appliance."""
        await self._wd.fetch_data()

    @callback
    def update_from_latest_data(self) -> None:
        """Calculate the time stamp for completion."""
        machine_state = self._wd.get_machine_state()
        now = utcnow()

        if (
            machine_state.value in {MachineState.Complete.value, MachineState.Standby.value}
            and self._running
        ):
            # Just finished a cycle, store now as end time
            self._running = False
            self._attr_native_value = now
            self._async_write_ha_state()

        if machine_state is MachineState.RunningMainCycle:
            self._running = True
            remaining_seconds = int(self._wd.get_attribute("Cavity_TimeStatusEstTimeRemaining"))
            new_timestamp = now + timedelta(seconds=remaining_seconds)

            # Only update if the new timestamp differs by more than 1 minute
            if self._attr_native_value is None or (
                isinstance(self._attr_native_value, datetime)
                and abs(new_timestamp - self._attr_native_value) > timedelta(seconds=60)
            ):
                self._attr_native_value = new_timestamp
                self._async_write_ha_state()


# -----------------------------------------------------------------------------------
# NEW: AirCon Sensors for Current Temperature & Current Humidity
# -----------------------------------------------------------------------------------

@dataclass
class WhirlpoolAirconSensorEntityDescription(SensorEntityDescription):
    """Describes Whirlpool Aircon sensor entity (temp/humidity)."""


AIRCON_SENSORS: tuple[WhirlpoolAirconSensorEntityDescription, ...] = (
    WhirlpoolAirconSensorEntityDescription(
        key="current_temperature",
        name="Current Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    WhirlpoolAirconSensorEntityDescription(
        key="current_humidity",
        name="Current Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
)


class AirConSensor(SensorEntity):
    """Sensor entity for Whirlpool AirCon attributes (temp/humidity)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, aircon: Aircon, description: WhirlpoolAirconSensorEntityDescription) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._aircon = aircon
        self._attr_unique_id = f"{aircon.said}-{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, aircon.said)},
            name=aircon.name if aircon.name else aircon.said,
            manufacturer="Whirlpool",
            model="Sixth Sense",
        )

    async def async_added_to_hass(self) -> None:
        """Register callback for aircon updates."""
        self._aircon.register_attr_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback."""
        self._aircon.unregister_attr_callback(self.async_write_ha_state)

    @property
    def available(self) -> bool:
        """Return True if aircon is online."""
        return self._aircon.get_online()

    @property
    def native_value(self) -> float | int | None:
        """Return the sensor value (temp or humidity)."""
        if self.entity_description.key == "current_temperature":
            return self._aircon.get_current_temp()
        if self.entity_description.key == "current_humidity":
            return self._aircon.get_current_humidity()
        return None


# -----------------------------------------------------------------------------------
# The platform setup, registering both washer/dryer and aircon sensors
# -----------------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: WhirlpoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Config flow entry for Whirlpool sensors."""
    entities: list[SensorEntity] = []
    appliances_manager = config_entry.runtime_data

    # Washer/Dryer sensors
    for washer_dryer in appliances_manager.washer_dryers:
        for description in SENSORS:
            entities.append(WasherDryerClass(washer_dryer, description))
        for description in SENSOR_TIMER:
            entities.append(WasherDryerTimeClass(washer_dryer, description))

    # AirCon sensors (new)
    for aircon in appliances_manager.aircons:
        for desc in AIRCON_SENSORS:
            entities.append(AirConSensor(aircon, desc))

    async_add_entities(entities)
