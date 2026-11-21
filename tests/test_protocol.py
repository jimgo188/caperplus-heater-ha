"""协议层测试：用真实设备快照的 48 字节验证解码，用本地假设备验证读/写流程。

不接触真机。运行：python3 tests/test_protocol.py
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import types

ROOT = "/home/ubuntu/hermes_work"
COMPONENT = f"{ROOT}/caperplus-ha/custom_components/caperplus_heater"
SNAPSHOT = str(Path(__file__).with_name("fixtures") / "snapshot.json")

# 让相对 import（from .const import ...）可用
pkg = types.ModuleType("cp")
pkg.__path__ = [COMPONENT]
sys.modules["cp"] = pkg
for mod in ("const", "gizwits"):
    spec = importlib.util.spec_from_file_location(f"cp.{mod}", f"{COMPONENT}/{mod}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"cp.{mod}"] = module
    spec.loader.exec_module(module)

giz = sys.modules["cp.gizwits"]
const = sys.modules["cp.const"]

snapshot = json.load(open(SNAPSHOT, encoding="utf-8"))
RAW = bytes.fromhex(snapshot["raw_hex"])
assert len(RAW) == 48, len(RAW)

failures: list[str] = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  ✗ {name}: {got!r} != {want!r}")
    else:
        print(f"  ✓ {name} = {got!r}")


# --------------------------------------------------------------- 1. 解码真实快照
print("1. 解码真实设备快照")
state = giz.GizwitsLocal.decode(RAW)
check("temp", state["temp"], 24.0)
check("temp1", state["temp1"], 24.11)
check("temp2", state["temp2"], 23.90)
check("temp_pid", state["temp_pid"], 24.0)
check("temp_min", state["temp_min"], 22.0)
check("temp_max", state["temp_max"], 34.0)
check("treatment_temp", state["treatment_temp"], 28.0)
check("power_para1", state["power_para1"], 98636)
check("power_value", state["power_value"], 38)
check("run_time", state["run_time"], 157)
check("dev_status", state["dev_status"], 1)
check("dev_config", state["dev_config"], 0)
check("rssi", state["rssi"], 7)
check("fault_temp", state["fault_temp"], 0)

# 快照里每个字段都要和 datapoints.json 的期望值一致
for name, meta in snapshot["values"].items():
    want = meta["value"]
    if name in const.TEMP_FIELDS:
        want = meta["raw_value"] / 100
    check(f"snapshot.{name}", state[name], want)

# --------------------------------------------------------------- 2. 位/故障解释
print("2. 状态位解释")
derived = {
    **state,
    "heating": bool(state["dev_status"] & 0x01),
    "water_out": bool(state["dev_status"] & 0x02),
    "paused": bool(state["dev_config"] & 0x01),
}
check("heating", derived["heating"], True)
check("water_out", derived["water_out"], False)
check("paused", derived["paused"], False)
check("faults(正常)", giz._describe_faults(state), [])
check(
    "faults(离水+探头1开路)",
    giz._describe_faults({**state, "water_out": True, "fault_temp": 0b1}),
    ["温度探头1 开路", "离水保护"],
)

# --------------------------------------------------------------- 3. 假设备：读 + 写
print("3. 假设备读/写")


class FakeDevice(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.buffer = bytearray(RAW)
        self.writes: list[bytes] = []
        self.flags: list[int] = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]

    def run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
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
            while True:
                if len(buf) < 8:
                    break
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
                cmd, payload = giz.parse_packet(packet)
                if cmd == 0x06:
                    conn.sendall(giz.build_packet(0x07, struct.pack(">H", len(passcode)) + passcode))
                elif cmd == 0x08:
                    # 真机确实会连发两个 0x09
                    conn.sendall(giz.build_packet(0x09, b"\x00"))
                    conn.sendall(giz.build_packet(0x09, b"\x00"))
                elif cmd == 0x90:
                    conn.sendall(giz.build_packet(0x91, b"\x03" + bytes(self.buffer)))
                elif cmd == 0x93:
                    self.writes.append(payload)
                    seq = payload[:4]
                    assert payload[4] == 0x01, f"control action byte: {payload[4]:#x}"
                    self.flags.append(int.from_bytes(payload[5:7], "big"))
                    body = payload[7:55]  # 48 字节全量

                    def apply_later(buf=body):
                        time.sleep(1.0)  # 真机写后 ≤2s 才生效
                        self.buffer[0:24] = buf

                    threading.Thread(target=apply_later, daemon=True).start()
                    conn.sendall(giz.build_packet(0x94, seq))


fake = FakeDevice()
fake.start()
time.sleep(0.2)

with giz.GizwitsLocal("127.0.0.1", port=fake.port) as dev:
    read_back = dev.read_state()
check("read temp", read_back["temp"], 24.0)
check("read heating", read_back["heating"], True)
check("read raw len", len(bytes.fromhex(read_back["raw"])), 48)

# 写目标温度 26.00 °C
dev = giz.GizwitsLocal("127.0.0.1", port=fake.port)
after = dev.write(temp_pid=26.0)
dev.close()
check("写入帧数量", len(fake.writes), 1)
check("写入帧长度", len(fake.writes[0]), 4 + 1 + 2 + 48)
check("action byte", fake.writes[0][4], 0x01)
check("attrFlags(temp_pid id=10)", fake.flags[0], 1 << 10)  # 位图按 id 编号
check("回读 temp_pid", after["temp_pid"], 26.0)
check("回写未破坏 power_para1", after["power_para1"], 98636)
check("回写未破坏 temp_min", after["temp_min"], 22.0)
check("回写未破坏 run_time", after["run_time"], 157)

# 暂停加热
dev = giz.GizwitsLocal("127.0.0.1", port=fake.port)
after = dev.write(dev_config=1)
dev.close()
check("attrFlags(dev_config id=4)", fake.flags[-1], 0x10)
check("暂停后 paused", bool(after["dev_config"] & 0x01), True)
check("暂停后 dev_status 未变", after["dev_status"], 1)

# 只读字段必须拒绝
dev = giz.GizwitsLocal("127.0.0.1", port=fake.port)
try:
    dev.write(temp=30.0)
    check("只读字段被拒绝", "没有抛错", "GizwitsError")
except giz.GizwitsError as err:
    check("只读字段被拒绝", "只读" in str(err), True)
finally:
    dev.close()

# --------------------------------------------------------------- 3b. 复现真机定版控制帧
print("3b. 复现真机抓到的 0x93 帧（temp_pid=23.90）")
# 用抓包里的原始 48 字节，避免手抄出错
REAL_DATA = bytes.fromhex(
    "2401000000010004"
    "0000095608980d48"
    "0af000000001814c"
    "0700000000630000"
    "00000960096b0960"
    "00000000000000a0"
)
check("抓包数据长度", len(REAL_DATA), 48)
REAL_SEQ = bytes.fromhex("00001a2b")
real_frame = bytes.fromhex("00000003" "3a" "00" "0093") + REAL_SEQ + b"\x01" + (1 << 10).to_bytes(2, "big") + REAL_DATA
check("抓包整帧长度", len(real_frame), 63)

built = giz.build_packet(0x93, REAL_SEQ + b"\x01" + (1 << 10).to_bytes(const.FLAG_BYTES, "big") + REAL_DATA)
check("FLAG_BYTES", const.FLAG_BYTES, 2)
check("重建帧与真机字节完全一致", built, real_frame)
check("长度字段 0x3a", built[4], 0x3A)
check("flags 字节位置", built[13:15], b"\x04\x00")
check("data 起点", built[15:17], b"\x24\x01")
check("data[10:12] = 23.90°C", int.from_bytes(REAL_DATA[10:12], "big"), 2390)

# --------------------------------------------------------------- 4. 发现包解析
print("4. 发现包解析")
resp = giz.build_packet(
    0x0004,
    struct.pack(">H", 22) + b"ABCDEFGHIJKLMNOPQRSTUV"
    + struct.pack(">H", 6) + bytes.fromhex("aabbccddeeff")
    + struct.pack(">H", 8) + b"0403000G"
    + struct.pack(">H", 32) + const.PRODUCT_KEY.encode(),
)
cmd, payload = giz.parse_packet(resp)
check("发现 cmd", cmd, 0x0004)
off, info = 0, {}
for key in ("uid", "mac", "firmware", "product_key"):
    n = int.from_bytes(payload[off:off + 2], "big")
    off += 2
    info[key] = payload[off:off + n]
    off += n
check("发现 mac", info["mac"].hex(":"), "aa:bb:cc:dd:ee:ff")
check("发现 firmware", info["firmware"].decode(), "0403000G")
check("发现 product_key", info["product_key"].decode(), const.PRODUCT_KEY)

fake.sock.close()

print()
if failures:
    print(f"失败 {len(failures)} 项：")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("全部通过")
