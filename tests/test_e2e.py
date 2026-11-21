"""端到端测试：在真正的 Home Assistant 里装上集成，对着假设备跑配置流程和实体。

    /home/ubuntu/hermes_work/.ha-venv/bin/python tests/test_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import socket
import struct
import sys
import threading
import time
from pathlib import Path

HA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HA_ROOT))

from homeassistant import bootstrap, core  # noqa: E402
from homeassistant.runner import RuntimeConfig  # noqa: E402

from custom_components.caperplus_heater import gizwits  # noqa: E402

SNAPSHOT = Path(__file__).with_name("fixtures") / "snapshot.json"
RAW = bytes.fromhex(json.loads(SNAPSHOT.read_text())["raw_hex"])

CONFIG_DIR = "/tmp/ha-e2e"
write_count = 0
writes: list[bytes] = []


class FakeHeater(threading.Thread):
    """Minimal Gizwits GAgent device on 127.0.0.1:12416."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.buffer = bytearray(RAW)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 12416))
        self.sock.listen(5)

    def run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn) -> None:
        global write_count
        buf = b""
        passcode = b"0123456789"
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while len(buf) >= 8:
                i, length, shift = 4, 0, 0
                while True:
                    b = buf[i]
                    i += 1
                    length |= (b & 0x7F) << shift
                    shift += 7
                    if not b & 0x80:
                        break
                total = i + length
                if len(buf) < total:
                    break
                packet, buf = buf[:total], buf[total:]
                cmd, payload = gizwits.parse_packet(packet)
                if cmd == 0x06:
                    conn.sendall(gizwits.build_packet(0x07, struct.pack(">H", len(passcode)) + passcode))
                elif cmd == 0x08:
                    conn.sendall(gizwits.build_packet(0x09, b"\x00"))
                    conn.sendall(gizwits.build_packet(0x09, b"\x00"))
                elif cmd == 0x90:
                    conn.sendall(gizwits.build_packet(0x91, b"\x03" + bytes(self.buffer)))
                elif cmd == 0x93:
                    write_count += 1
                    writes.append(payload)
                    self.buffer[:] = payload
                    conn.sendall(gizwits.build_packet(0x94, b"\x00"))


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.levelname} {record.name}: {record.getMessage()}")


async def main() -> int:
    failures: list[str] = []

    def check(name, got, want):
        if got != want:
            failures.append(f"{name}: {got!r} != {want!r}")
            print(f"  ✗ {name}: {got!r} != {want!r}", flush=True)
        else:
            print(f"  ✓ {name} = {got!r}", flush=True)

    Path(CONFIG_DIR, "custom_components").mkdir(parents=True, exist_ok=True)
    shutil.rmtree(Path(CONFIG_DIR, ".storage"), ignore_errors=True)  # 从干净实例开始
    link = Path(CONFIG_DIR, "custom_components", "caperplus_heater")
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(HA_ROOT / "custom_components" / "caperplus_heater")
    Path(CONFIG_DIR, "configuration.yaml").write_text(
        "homeassistant:\n  name: E2E\n  time_zone: Asia/Shanghai\n", encoding="utf-8"
    )

    handler = ListHandler()
    logging.getLogger("custom_components.caperplus_heater").addHandler(handler)
    logging.getLogger("custom_components.caperplus_heater").setLevel(logging.DEBUG)

    fake = FakeHeater()
    fake.start()
    time.sleep(0.2)

    print("1. 启动 Home Assistant", flush=True)
    runtime = RuntimeConfig(config_dir=CONFIG_DIR, skip_pip=True)
    hass: core.HomeAssistant = await bootstrap.async_setup_hass(runtime)
    assert hass is not None
    await hass.async_start()
    print(f"  HA {core.__version__} 启动完成", flush=True)

    print("2. 配置流程", flush=True)
    flow = await hass.config_entries.flow.async_init(
        "caperplus_heater", context={"source": "user"}
    )
    check("flow type", flow["type"], "form")
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"host": "127.0.0.1", "name": "鱼缸加热棒"}
    )
    await hass.async_block_till_done()
    check("flow result", result["type"], "create_entry")
    entry = hass.config_entries.async_entries("caperplus_heater")
    check("entry 数量", len(entry), 1)
    entry_id = entry[0].entry_id

    print("3. 实体", flush=True)
    await asyncio.sleep(1.5)
    await hass.async_block_till_done()
    states = {s.entity_id: s for s in hass.states.async_all()}
    mine = {k: v for k, v in states.items() if "jia_re_bang" in k or "caperplus" in k}
    for entity_id, state in sorted(mine.items()):
        print(f"    {entity_id} = {state.state}", flush=True)
    if climate_id := next((e for e in mine if e.startswith("climate.")), None):
        print("    属性:", dict(mine[climate_id].attributes), flush=True)
    climate_id = next((e for e in mine if e.startswith("climate.")), None)
    check("温控实体存在", climate_id is not None, True)
    if climate_id:
        check("当前水温", mine[climate_id].attributes.get("current_temperature"), 24.0)
        check("目标温度", mine[climate_id].attributes.get("temperature"), 24.0)
        check("hvac_action", mine[climate_id].attributes.get("hvac_action"), "heating")
    check("水温传感器", any(k.endswith("_water_temperature") for k in mine), True)
    check("功率传感器", any(k.endswith("_heating_power") for k in mine), True)
    check("离水告警实体", any(k.endswith("_out_of_water") for k in mine), True)

    print("4. 通过服务改温度", flush=True)
    before = write_count
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": climate_id, "temperature": 26.5},
        blocking=True,
    )
    await hass.async_block_till_done()
    check("写入帧数 +1", write_count, before + 1)
    if writes:
        payload = writes[-1]
        check("写入帧长度", len(payload), 48)
        check("temp_pid 已改", int.from_bytes(payload[10:12], "big"), 2650)
        check("power_para1 未被破坏", int.from_bytes(payload[20:24], "big"), 98636)
    await asyncio.sleep(0.5)
    state = hass.states.get(climate_id)
    check("实体目标温度更新", state.attributes.get("temperature"), 26.5)

    print("5. 关闭 = 暂停加热", flush=True)
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": climate_id, "hvac_mode": "off"}, blocking=True
    )
    await hass.async_block_till_done()
    await asyncio.sleep(0.3)
    state = hass.states.get(climate_id)
    check("状态为 off", state.state, "off")
    if writes:
        check("dev_config bit0 = 1", writes[-1][4] & 0x01, 1)

    print("6. 卸载", flush=True)
    unloaded = await hass.config_entries.async_unload(entry_id)
    check("卸载成功", unloaded, True)
    await hass.async_block_till_done()

    fake.sock.close()
    await hass.async_stop(force=True)

    print()
    errors = [r for r in handler.records if r.startswith("ERROR")]
    if errors:
        print("集成日志中的 ERROR：")
        for line in errors[:10]:
            print("  ", line)
    if failures:
        print(f"失败 {len(failures)} 项")
        for f in failures:
            print("  -", f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
