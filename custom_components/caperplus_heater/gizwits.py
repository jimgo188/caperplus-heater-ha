"""Blocking Gizwits GAgent LAN client for the Caperplus T1+ heater.

Protocol (verified against the real device, firmware 0403000G):

    frame: 00 00 00 03 | varlen(len) | flag(00) | cmd(2B BE) | payload
            len = 1 (flag) + 2 (cmd) + len(payload)

    discovery   UDP 12414  ->  0x0004 reply: varlen(uid) varlen(mac)
                                              varlen(firmware) varlen(product_key)
    passcode    0x06       ->  0x07: uint16 BE length + passcode
    login       0x08       ->  0x09: first byte 0 == ok (device sends it twice)
    read state  0x90 (0x02)->  0x91: action byte + 48 bytes
    write state 0x93 (48B) ->  0x94: first byte is the return code

All I/O here is blocking on purpose: Home Assistant runs it in an executor.
"""

from __future__ import annotations

import logging
import socket
import struct
import time

from .const import (
    ATTRS,
    CONNECT_TIMEOUT,
    DATA_LEN,
    FAULT_FIELDS,
    PRODUCT_KEY,
    TCP_PORT,
    TEMP_FIELDS,
    UDP_PORT,
    WRITABLE_LEN,
)

_LOGGER = logging.getLogger(__name__)

DISCOVERY_REQUEST = b"\x00\x00\x00\x03\x03\x00\x00\x03"


# --------------------------------------------------------------------------- framing
def varlen(n: int) -> bytes:
    """LEB128, as used by Gizwits for the length field."""
    if n < 128:
        return bytes([n])
    out = []
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(0x80 | b if n else b)
        if not n:
            return bytes(out)


def build_packet(cmd: int, payload: bytes = b"") -> bytes:
    body = 1 + 2 + len(payload)
    return b"\x00\x00\x00\x03" + varlen(body) + b"\x00" + cmd.to_bytes(2, "big") + payload


def parse_packet(data: bytes) -> tuple[int | None, bytes | None]:
    if not data.startswith(b"\x00\x00\x00\x03"):
        return None, None
    i, length, shift = 4, 0, 0
    while True:
        if i >= len(data):
            return None, None
        b = data[i]
        i += 1
        length |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            break
    if i + 3 > len(data):
        return None, None
    i += 1  # flag
    cmd = int.from_bytes(data[i:i + 2], "big")
    return cmd, data[i + 2:i + length + 2]


# --------------------------------------------------------------------------- errors
class GizwitsError(Exception):
    """Protocol level failure."""


class DeviceBusy(GizwitsError):
    """Device unreachable / occupied (vendor app open, rebooting...)."""


# --------------------------------------------------------------------------- discovery
def _broadcast_targets() -> tuple[str, ...]:
    targets = {"255.255.255.255"}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            local_ip = probe.getsockname()[0]
        prefix = local_ip.rsplit(".", 1)[0]
        targets.add(f"{prefix}.255")
    except OSError:
        pass
    return tuple(targets)


def discover(timeout: float = 4.0) -> list[dict]:
    """Broadcast for Gizwits devices; returns list of info dicts."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1.0)
    found: dict[str, dict] = {}
    targets = _broadcast_targets()
    start = time.monotonic()
    try:
        while time.monotonic() - start < timeout:
            for target in targets:
                try:
                    sock.sendto(DISCOVERY_REQUEST, (target, UDP_PORT))
                except OSError:
                    pass
            try:
                data, (ip, _) = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            cmd, payload = parse_packet(data)
            if cmd != 0x0004 or payload is None:
                continue
            info: dict = {"ip": ip}
            off = 0
            for key in ("uid", "mac", "firmware", "product_key"):
                if off + 2 > len(payload):
                    break
                n = int.from_bytes(payload[off:off + 2], "big")
                off += 2
                if off + n > len(payload):
                    break
                value = payload[off:off + n]
                off += n
                if key == "uid":
                    info["uid"] = value.hex()
                elif key == "mac":
                    info["mac"] = value.hex(":")
                else:
                    info[key] = value.decode("ascii", "ignore")
            if info.get("product_key"):
                found[ip] = info
    finally:
        sock.close()
    return list(found.values())


# --------------------------------------------------------------------------- session
class GizwitsLocal:
    """One-shot session: connect -> login -> read -> close."""

    def __init__(self, host: str, port: int = TCP_PORT, timeout: float = CONNECT_TIMEOUT):
        self.host, self.port, self.timeout = host, port, timeout
        self._buf = b""
        self._raw: bytes | None = None
        try:
            self._sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as err:
            raise DeviceBusy(f"连接 {host}:{port} 失败：{err}") from err
        self._sock.settimeout(timeout)

    # -- plumbing
    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "GizwitsLocal":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _recv_packet(self) -> tuple[int, bytes]:
        deadline = time.monotonic() + self.timeout
        while True:
            packet = self._pop()
            if packet is not None:
                return packet
            if time.monotonic() > deadline:
                raise DeviceBusy("设备没有回应")
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout as err:
                raise DeviceBusy("设备没有回应") from err
            if not chunk:
                raise DeviceBusy("设备断开连接")
            self._buf += chunk

    def _pop(self) -> tuple[int, bytes] | None:
        if len(self._buf) < 8:
            return None
        i, length, shift = 4, 0, 0
        while True:
            if i >= len(self._buf):
                return None
            b = self._buf[i]
            i += 1
            length |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        total = i + length
        if len(self._buf) < total:
            return None
        packet, self._buf = self._buf[:total], self._buf[total:]
        return parse_packet(packet)

    def _request(
        self, cmd: int, payload: bytes = b"", want: int | tuple[int, ...] | None = None
    ) -> tuple[int, bytes]:
        """Send once and wait for `want`, discarding stale frames.

        The device answers a login with two 0x09 frames, so the next request
        would otherwise read the leftover one. Never re-send here: a retried
        0x93 would apply a write twice.
        """
        wanted = None if want is None else ((want,) if isinstance(want, int) else want)
        self._sock.sendall(build_packet(cmd, payload))
        last = None
        for _ in range(6):
            got, data = self._recv_packet()
            last = got
            if wanted is None or got in wanted:
                return got, data
        expected = "/".join(f"0x{c:02x}" for c in wanted) if wanted else "任一"
        raise GizwitsError(f"等待 cmd={expected} 超时，最后收到 0x{last:02x}" if last else "无响应")

    # -- protocol
    def login(self) -> bytes:
        _, payload = self._request(0x06, b"", 0x07)
        if not payload or len(payload) < 2:
            raise GizwitsError("取 passcode 失败")
        size = struct.unpack(">H", payload[:2])[0]
        if size == 0 or len(payload) < 2 + size:
            raise GizwitsError("passcode 为空")
        passcode = payload[2:2 + size]
        _, resp = self._request(0x08, struct.pack(">H", len(passcode)) + passcode, 0x09)
        if resp and resp[0] != 0:
            raise GizwitsError(f"登录被拒绝，返回码 {resp[0]}")
        return passcode

    def read_raw(self) -> bytes:
        if self._raw is None:
            self.login()
            got, payload = self._request(0x90, b"\x02", want=0x91)
            if not payload:
                raise GizwitsError(f"读状态失败（cmd=0x{got:02x}）")
            self._raw = payload[1:]  # drop action byte
            if len(self._raw) < DATA_LEN:
                raise GizwitsError(f"状态长度异常：{len(self._raw)}")
        return self._raw

    # -- decoding
    @staticmethod
    def decode(raw: bytes) -> dict:
        out: dict = {}
        for name, dtype, off, length, bit_off, unit, _writable, _desc in ATTRS:
            if off + length > len(raw):
                continue
            if unit == "bit":
                value = (raw[off] >> bit_off) & ((1 << length) - 1)
                if dtype == "bool":
                    value = bool(value)
            else:
                value = int.from_bytes(raw[off:off + length], "big")
                if name in TEMP_FIELDS:
                    value = value / 100.0
            out[name] = value
        return out

    def read_state(self) -> dict:
        state = self.decode(self.read_raw())
        state["heating"] = bool(state.get("dev_status", 0) & 0x01)
        state["water_out"] = bool(state.get("dev_status", 0) & 0x02)
        state["paused"] = bool(state.get("dev_config", 0) & 0x01)
        state["any_fault"] = any(state.get(name, 0) for name in FAULT_FIELDS)
        state["faults"] = _describe_faults(state)
        state["raw"] = bytes(self._raw).hex()
        return state

    # -- writing
    def write(self, **values) -> dict:
        """Write datapoints with a Gizwits partial-update control frame.

        Frame payload (cmd 0x93), per the Gizwits p0 protocol:
            seq(4B) + 0x01 (control action) + attrFlags(bitmap) + attrVals

        attrFlags is a big-endian bitmap indexed by datapoint id. attrVals must be
        the *writable prefix* of the attribute buffer (here 24 bytes, ending at
        power_para1) — this heater silently ignores a frame that also carries the
        read-only tail, answering only with the sequence number. The buffer is
        read first and only the target field is patched, so power_para1 (power
        calibration, 98636) survives.

        Returns the state read back from the device. Raises GizwitsError unless
        the readback actually shows the new value: the ACK alone proves nothing.
        """
        from .const import ATTR_BY_NAME, ATTR_IDS

        unknown = set(values) - set(ATTR_BY_NAME)
        if unknown:
            raise GizwitsError(f"未知数据点：{sorted(unknown)}")

        expected: dict[str, float | int] = {}
        self._raw = None
        raw = bytearray(self.read_raw())
        flags = 0
        for name, value in values.items():
            _n, dtype, off, length, bit_off, unit, writable, _desc = ATTR_BY_NAME[name]
            if not writable:
                raise GizwitsError(f"{name} 是只读字段")
            if name in TEMP_FIELDS:
                value = int(round(float(value) * 100))
            if unit == "bit":
                mask = ((1 << length) - 1) << bit_off
                current = int.from_bytes(raw[:2], "big")
                current = (current & ~mask) | ((int(value) << bit_off) & mask)
                raw[0:2] = current.to_bytes(2, "big")
            else:
                raw[off:off + length] = int(value).to_bytes(length, "big")
            flags |= 1 << ATTR_IDS[name]
            expected[name] = value / 100 if name in TEMP_FIELDS else int(value)

        flag_bytes = max(ATTR_IDS.values()) // 8 + 1
        seq = struct.pack(">I", int(time.time() * 1000) & 0xFFFF)
        payload = seq + b"\x01" + flags.to_bytes(flag_bytes, "big") + bytes(raw[:WRITABLE_LEN])

        got, resp = self._request(0x93, payload, want=(0x93, 0x94))
        _LOGGER.debug("控制帧 %s → 应答 cmd=0x%02x %s", payload.hex(), got, resp.hex())
        if len(resp) >= 4 and resp[:4] != seq:
            raise GizwitsError("控制应答序号不匹配")

        self._raw = None
        self.close()  # the device accepts a single local connection only
        with GizwitsLocal(self.host, self.port, self.timeout) as verify:
            state = verify.read_state()

        wrong = [
            f"{name}={state.get(name)!r}（期望 {want!r}）"
            for name, want in expected.items()
            if abs(float(state.get(name) or 0) - float(want)) > 0.01
        ]
        if wrong:
            raise GizwitsError(
                f"设备没有接受写入（应答 cmd=0x{got:02x} {resp.hex() or '空'}），"
                "回读值未变化：" + ", ".join(wrong)
            )
        return state


def _describe_faults(state: dict) -> list[str]:
    from .const import FAULT_TEMP_BITS

    messages: list[str] = []
    temp_fault = state.get("fault_temp", 0)
    for bit, text in FAULT_TEMP_BITS.items():
        if temp_fault & (1 << bit):
            messages.append(text)
    if state.get("fault_heater"):
        messages.append(f"加热棒异常（0x{state['fault_heater']:02x}）")
    if state.get("fault_power"):
        messages.append(f"功率检测异常（0x{state['fault_power']:02x}）")
    if state.get("fault_zero"):
        messages.append(f"过零检测异常（0x{state['fault_zero']:02x}）")
    if state.get("water_out"):
        messages.append("离水保护")
    return messages


def resolve_device(host: str | None) -> dict:
    """Find the device: broadcast first, fall back to the given host."""
    devices = discover()
    if host:
        for dev in devices:
            if dev["ip"] == host:
                return dev
    if not host:
        if len(devices) == 1:
            return devices[0]
        if len(devices) > 1:
            raise GizwitsError("发现多台设备，请指定 IP")
        raise DeviceBusy("没有发现设备")

    # host given but discovery missed it: verify it is reachable at all
    with GizwitsLocal(host):
        pass
    return {"ip": host, "product_key": PRODUCT_KEY, "mac": None, "firmware": None}
