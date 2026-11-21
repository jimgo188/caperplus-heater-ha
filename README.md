# Caperplus Heater — Home Assistant 集成（光特亿 / 鱼乐世界）

把「鱼乐世界」App 里的光特亿 WiFi 加热棒（T1+，product_key `7eef63f981fd4a10ad967af20c5f5855`）
接进 Home Assistant。**纯局域网**：不需要账号、不需要厂商云、不需要 App 在跑。

设备本身跑的是机智云 GAgent 固件，集成直接说 GAgent 的局域网协议（UDP 12414 发现 + TCP 12416 控制）。

## 实体

| 实体 | 说明 |
|---|---|
| `climate.<名称>` | 温控：当前水温、目标温度（0.5 °C 步进）、加热/待机/关闭 |
| `sensor.<名称>_水温` | 当前水温（来自设备 `temp` 字段，即设备自己算的水温） |
| `sensor.<名称>_加热功率` | 瞬时加热功率 W |
| `binary_sensor.<名称>_加热中` | `dev_status` bit0 |
| `binary_sensor.<名称>_离水保护` | `dev_status` bit1，`problem` 类，离水断电时告警 |
| `binary_sensor.<名称>_故障` | 任一 `fault_*` 非 0，属性里有明细 |
| 诊断 | 探头1/探头2、信号强度、运行时间 |

关闭（`HVACMode.OFF`）写的是 `dev_config` bit0 = **强制暂停加热**，不是切断电源；加热棒的硬件保护仍然有效。

## 安装

### HACS（推荐）

1. HACS → Integrations → 右上角 ⋮ → **Custom repositories**
2. 添加 `https://github.com/jimgo188/caperplus-heater-ha`，类别 **Integration**
3. 安装后重启 Home Assistant
4. 设置 → 设备与服务 → 添加集成 → 搜 **Caperplus Heater**

### 手动

把 `custom_components/caperplus_heater/` 拷到 HA 的 `/config/custom_components/` 下，重启 HA。

## 配置

添加集成时填设备 IP（可在路由器后台找，主机名一般以 `ESP_` 开头），或留空让集成广播发现。
建议在路由器里给加热棒固定 IP / DHCP 保留。

**添加前请先在鱼乐世界 App 里退出该设备的详情页** —— 设备同一时间只接受一个本地连接。

## 已知限制

- **轮询**：设备不主动推送，集成每 20 秒连接一次读全部状态（一次往返约 0.9 s）。
- 设备只允许一个本地连接，App 打开设备页时 HA 会短暂显示不可用（连续 3 次失败才降级）。
- `power_consumption`（总电量）和 `run_time`（运行小时）在固件 `0403000G` 上基本不刷新，只作诊断。
- `pid_param` / `power_freq` 两个字段的官方定义和固件实际行为不符，没有暴露。

## 先决条件 / 排错

- **不要让两套温控打架**：如果 HA 里原来有「按水温开关智能插座」的自动化给这根加热棒供电，请把它关掉，让加热棒自己的温控闭环；插座只保留超温断电/告警的守护作用。
- 调试日志：设置 → 设备与服务 → Caperplus Heater → 启用调试日志。

## 协议摘要

```
00 00 00 03 | varlen(len) | flag(00) | cmd(2B BE) | payload
发现   UDP 12414 -> 0x0004: varlen(uid) varlen(mac) varlen(firmware) varlen(product_key)
passcode 0x06 -> 0x07: uint16 BE len + passcode
登录     0x08 -> 0x09: 首字节 0 成功（⚠ 设备会连发两个 0x09）
读状态   0x90(0x02) -> 0x91: 动作码 + 48 字节
写状态   0x93 -> 0x94: 应答回带 seq
         payload = seq(4B) + 0x01(控制动作) + attrFlags(2B 位图, 按数据点 id) + attrVals(48B 全量)
         整帧 63 字节 = 8 字节帧头 + 55 字节 payload（长度字段 0x3a）
```

写入不是裸发 48 字节：必须带 4 字节 seq、控制动作字节 `0x01` 和 attrFlags 位图，否则设备会拒绝（这就是 v1.0.0 的 bug）。
位图宽度由「可写数据点的最大 id」决定：本产品 id 0..15 可写 → **2 字节**。设备按固定 7 字节头切 payload
（位图 = `payload[5:7]`，数据 = `payload[7:55]`），发 4 或 8 字节位图会把数据区整体错位，设备看到的是空掩码
——只回一个序号、一个字段都不写。
attrVals 是 48 字节全量：先读一次、只改目标字段、其余原样发回，用全 0 缓冲区会清掉 `power_para1` 功率校准值。
写入成功与否只认回读值，不认 ACK：设备写后要 1~2 s 才生效，且它随后推送的 `0x91` 是**写之前的快照**，
所以集成会在 5 s 内反复用新的 `0x90` 回读，直到读到新值才算成功。
注意 App 和本地同时操作会打架：App 打开设备页时有时会把设定温度同步回旧值。

致谢：[chrisc123/jebao_aqua-homeassistant](https://github.com/chrisc123/jebao_aqua-homeassistant)、
[richmirrely/ha-afire](https://github.com/richmirrely/ha-afire) —— 同平台的协议参考实现。
