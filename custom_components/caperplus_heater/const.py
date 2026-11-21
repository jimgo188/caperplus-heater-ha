"""Constants and datapoint definitions for the Caperplus (鱼乐世界) heater."""

from __future__ import annotations

DOMAIN = "caperplus_heater"
PLATFORMS = ["climate", "sensor", "binary_sensor"]

CONF_HOST = "host"

MANUFACTURER = "光特亿 Caperplus"
MODEL = "T1+ WiFi 加热棒"
PRODUCT_KEY = "7eef63f981fd4a10ad967af20c5f5855"
PRODUCT_NAME = "T1plus_2"

TCP_PORT = 12416
UDP_PORT = 12414
DATA_LEN = 48

# 设备一次「连接+登录+读」约 0.9 s，App 侧也是十几秒量级刷新
DEFAULT_SCAN_INTERVAL = 20
SCAN_INTERVAL = DEFAULT_SCAN_INTERVAL
DISCOVERY_TIMEOUT = 4.0
CONNECT_TIMEOUT = 6.0

# 目标温度兜底范围（设备自己的安全范围优先）
FALLBACK_MIN_TEMP = 18.0
FALLBACK_MAX_TEMP = 32.0
TARGET_TEMP_STEP = 0.5

# name, data_type, byte_offset, len, bit_offset, unit, writable, 说明
ATTRS: list[tuple[str, str, int, int, int, str, bool, str]] = [
    ("to_mcu", "uint8", 0, 1, 0, "byte", True, "过零检测 debug"),
    ("temp_show", "uint8", 1, 1, 0, "byte", True, "预留"),
    ("temp_unit", "uint8", 2, 1, 0, "byte", True, "温度显示单位 0:C 1:F 2:K 3:R"),
    ("temp_pcb", "uint8", 3, 1, 0, "byte", True, "预留"),
    ("dev_config", "uint8", 4, 1, 0, "byte", True, "b0 强制暂停加热"),
    ("dev_status", "uint8", 5, 1, 0, "byte", True, "b0 加热中, b1 离水"),
    ("treatment_mode", "uint8", 6, 1, 0, "byte", True, "治疗模式"),
    ("treatment_para", "uint8", 7, 1, 0, "byte", True, "每小时 +/-0.5°C"),
    ("reserved1", "uint8", 8, 1, 0, "byte", True, "预留"),
    ("reserved2", "uint8", 9, 1, 0, "byte", True, "预留"),
    ("temp_pid", "uint16", 10, 2, 0, "byte", True, "设定恒温温度"),
    ("temp_min", "uint16", 12, 2, 0, "byte", True, "安全范围最低"),
    ("temp_max", "uint16", 14, 2, 0, "byte", True, "安全范围最高"),
    ("treatment_temp", "uint16", 16, 2, 0, "byte", True, "治疗温度"),
    ("power_para2", "uint16", 18, 2, 0, "byte", True, "功率校准预估值"),
    ("power_para1", "uint32", 20, 4, 0, "byte", True, "功率校准参数（勿动）"),
    ("rssi", "uint8", 24, 1, 0, "byte", False, "信号强度"),
    ("to_app", "uint8", 25, 1, 0, "byte", False, "保留"),
    ("to_server", "uint8", 26, 1, 0, "byte", False, "数据保存开关"),
    ("push", "uint8", 27, 1, 0, "byte", False, "预留"),
    ("pid_param", "uint8", 28, 1, 0, "byte", False, "固件里其实是心跳计数"),
    ("power_freq", "uint8", 29, 1, 0, "byte", False, "固件里其实是占空比"),
    ("fault_temp", "uint8", 30, 1, 0, "byte", False, "温度探头异常"),
    ("fault_heater", "uint8", 31, 1, 0, "byte", False, "加热棒异常"),
    ("fault_power", "uint8", 32, 1, 0, "byte", False, "功率检测异常"),
    ("fault_zero", "uint8", 33, 1, 0, "byte", False, "过零检测异常"),
    ("temp", "uint16", 34, 2, 0, "byte", False, "当前温度"),
    ("temp1", "uint16", 36, 2, 0, "byte", False, "探头1"),
    ("temp2", "uint16", 38, 2, 0, "byte", False, "探头2"),
    ("power_value", "uint16", 40, 2, 0, "byte", False, "当前功率 W"),
    ("power_consumption", "uint16", 42, 2, 0, "byte", False, "总用电量（未实现）"),
    ("run_time", "uint32", 44, 4, 0, "byte", False, "运行小时"),
]

# 机智云控制帧里的 attrFlags 位图按数据点 id 编号，id 即 ATTRS 的顺序（0..31）
ATTR_IDS = {name: index for index, (name, *_rest) in enumerate(ATTRS)}
ATTR_BY_NAME = {attr[0]: attr for attr in ATTRS}

TEMP_FIELDS = {"temp", "temp1", "temp2", "temp_pid", "temp_min", "temp_max", "treatment_temp"}

FAULT_FIELDS = ("fault_temp", "fault_heater", "fault_power", "fault_zero")

FAULT_TEMP_BITS = {
    0: "温度探头1 开路",
    1: "温度探头2 开路",
    2: "温度探头1 短路",
    3: "温度探头2 短路",
    4: "温度异常",
}
