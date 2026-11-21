"""实体逻辑测试（需要装好 homeassistant 的 venv 才能跑）。

    /path/to/venv/bin/python tests/test_entity.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

HA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HA_ROOT))

from custom_components.caperplus_heater import binary_sensor, climate, sensor  # noqa: E402
from custom_components.caperplus_heater import gizwits  # noqa: E402

SNAPSHOT = Path(__file__).with_name("fixtures") / "snapshot.json"
state = gizwits.GizwitsLocal.decode(bytes.fromhex(json.loads(SNAPSHOT.read_text())["raw_hex"]))
state["heating"] = bool(state["dev_status"] & 0x01)
state["water_out"] = bool(state["dev_status"] & 0x02)
state["paused"] = bool(state["dev_config"] & 0x01)
state["any_fault"] = False
state["faults"] = []

failures: list[str] = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: {got!r} != {want!r}")
        print(f"  ✗ {name}: {got!r} != {want!r}")
    else:
        print(f"  ✓ {name} = {got!r}")


class FakeCoordinator:
    def __init__(self, data):
        self.data = data
        self.calls: list[tuple] = []

    async def async_set_target_temperature(self, value):
        self.calls.append(("target", value))

    async def async_set_paused(self, value):
        self.calls.append(("paused", value))


entry = types.SimpleNamespace(
    data={"host": "192.168.1.50", "name": "鱼缸加热棒", "mac": "aa:bb:cc:dd:ee:ff",
          "firmware": "0403000G"},
    entry_id="test",
    title="鱼缸加热棒",
)

print("1. 温控实体")
coordinator = FakeCoordinator(dict(state))
thermostat = climate.CaperplusThermostat(coordinator, entry)
check("当前水温", thermostat.native_current_temperature, 24.0)
check("目标温度", thermostat.native_target_temperature, 24.0)
check("最小温度", thermostat.min_temp, 22.0)
check("最大温度", thermostat.max_temp, 34.0)
check("模式", thermostat.hvac_mode.value, "heat")
check("动作", thermostat.hvac_action.value, "heating")
check("属性-功率", thermostat.extra_state_attributes["当前功率_w"], 38)
check("属性-固件", thermostat.extra_state_attributes["固件"], "0403000G")
check("unique_id", thermostat.unique_id, "aa:bb:cc:dd:ee:ff_thermostat")

coordinator.data = {**state, "heating": False}
check("停止加热时动作", thermostat.hvac_action.value, "idle")

coordinator.data = {**state, "paused": True}
check("暂停时模式", thermostat.hvac_mode.value, "off")
check("暂停时动作", thermostat.hvac_action.value, "off")

coordinator.data = {**state, "water_out": True}
check("离水时动作", thermostat.hvac_action.value, "idle")

print("2. 目标温度钳制与写入")
coordinator.data = dict(state)
coordinator.calls.clear()
asyncio.run(thermostat.async_set_temperature(temperature=26.0))
asyncio.run(thermostat.async_set_temperature(temperature=99.0))
asyncio.run(thermostat.async_set_temperature(temperature=1.0))
check("三次写入", coordinator.calls, [("target", 26.0), ("target", 34.0), ("target", 22.0)])
asyncio.run(thermostat.async_set_hvac_mode(climate.HVACMode.OFF))
asyncio.run(thermostat.async_set_hvac_mode(climate.HVACMode.HEAT))
check("模式写入", coordinator.calls[-2:], [("paused", True), ("paused", False)])

print("3. 传感器")
sensor_entities = {}
for desc in sensor.SENSORS:
    entity = sensor.CaperplusSensorEntity(coordinator, entry, desc)
    sensor_entities[desc.key] = entity
check("水温传感器", sensor_entities["water_temperature"].native_value, 24.0)
check("功率传感器", sensor_entities["power"].native_value, 38)
check("探头1", sensor_entities["probe1"].native_value, 24.11)
check("运行时间", sensor_entities["run_time"].native_value, 157)

print("4. 二元传感器")
bin_entities = {}
for desc in binary_sensor.BINARY_SENSORS:
    bin_entities[desc.key] = binary_sensor.CaperplusBinarySensorEntity(coordinator, entry, desc)
check("加热中", bin_entities["heating"].is_on, True)
check("离水", bin_entities["water_out"].is_on, False)
check("故障", bin_entities["fault"].is_on, False)

print()
if failures:
    print(f"失败 {len(failures)} 项")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("全部通过")
