---
name: esp32-hid-flash
description: 自动检测、编译并烧录 ESP32-S3 远程 HID 键鼠与 64KB 虚拟 U 盘固件。当用户需要烧录固件、重新刷机、选择硬件型号（DevKitC-1/N16R8/Single-USB Zero）、排查串口或权限问题时触发此技能。
---

# ESP32-S3 固件编译与烧录指南

本技能负责检测本地 PlatformIO 编译环境、识别开发板串口设备，并自动完成固件编译与烧录。

## 目标硬件与接口说明

- **ESP32-S3 具备两个 Type-C 接口**：
  - **UART / COM 口**：用于固件烧录与串口日志（波特率 115200）。
  - **USB-OTG 原生口**：运行阶段插在受控目标电脑上，枚举为键鼠 + 虚拟 U 盘。
- **环境预设**（在 `platformio.ini` 中定义）：
  - `esp32-s3-devkitc-1`（默认推荐）：标准双口板，4MB/8MB Flash。
  - `esp32-s3-n16r8`：常见 16MB Flash + 8MB OPI PSRAM 板卡。
  - `esp32-s3-single-usb`：单口无独立串口芯片板卡（如 ESP32-S3-Zero、SuperMini）。

---

## 自动化执行流程

使用脚本 `scripts/flash.py` 一键处理编译与烧录：

### 1. 检查编译环境与可用串口

执行：
```bash
python3 skills/esp32-hid-flash/scripts/flash.py --check-only
```
- 确认 PlatformIO Core (`pio`) 处于可用状态（自动检测系统 PATH 或 `~/.platformio/penv/bin/pio`）。
- 确认系统检测到的串口设备（如 `/dev/ttyACM0`、`/dev/ttyUSB0`）。

### 2. 编译并烧录固件

根据用户的板型执行：
```bash
# 默认板型（DevKitC-1 双 Type-C）
python3 skills/esp32-hid-flash/scripts/flash.py --env esp32-s3-devkitc-1

# N16R8 大内存板型
python3 skills/esp32-hid-flash/scripts/flash.py --env esp32-s3-n16r8

# 单 USB 口板卡（ESP32-S3-Zero 等）
python3 skills/esp32-hid-flash/scripts/flash.py --env esp32-s3-single-usb

# 若有多块串口设备，显式指定端口：
python3 skills/esp32-hid-flash/scripts/flash.py --env esp32-s3-devkitc-1 --port /dev/ttyACM0
```

### 3. 常见异常与排查对策

1. **未检测到串口设备**：
   - 检查 USB 数据线是否支持数据传输（非仅充电线）。
   - 确认连接的是开发板的 **UART 端口**。
   - 按住板载 `BOOT (GPIO0)` 键不放，再插入 USB 或按一下 `RST (EN)` 键，强制芯片进入 ROM Bootloader 烧录模式。
2. **Linux 串口权限拒绝 (`Permission Denied`)**：
   - 当前用户需加入 dialout 组：`sudo usermod -a -G dialout $USER`（需重登生效），或临时执行：`sudo chmod 666 /dev/ttyUSB* /dev/ttyACM*`。
3. **烧录完成后接线切换**：
   - 烧录成功后，提示用户将开发板从 UART 口切换/引出 **原生 USB-OTG 口** 插入受控电脑。
