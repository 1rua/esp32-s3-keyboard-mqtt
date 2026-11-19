---
name: esp32-hid-init
description: 初始化 ESP32-S3 硬件并完成动态配网（Wi-Fi 及 MQTT 参数持久化至 NVS 闪存）。当用户需要配置网络、更换 Wi-Fi、配置巴法云或自建 EMQX Broker、重置设备网络时触发此技能。
---

# ESP32-S3 设备初始化与动态配网指南

本技能负责指导或自动化完成 ESP32-S3 开发板的 Wi-Fi 与 MQTT 参数配置，将其安全持久化至板载 NVS（Non-Volatile Storage）闪存中。

## 必要配置信息

向用户收集以下最简配置信息（或直接采纳用户提供的参数）：

### 方案 A：巴法云 (Bemfa) 极简模式（推荐新手）
- **Wi-Fi SSID**：2.4GHz Wi-Fi 名称
- **Wi-Fi 密码**：Wi-Fi 密码（无密码可留空）
- **巴法云私钥 (Client ID)**：巴法云控制台获取的私钥（UID）
- **主题名称**（可选，默认自动分配）：
  - 上行主题 `topic_up`（默认：`hidUp001`）
  - 下行主题 `topic_down`（默认：`hidDown001`）
  *(注：巴法云中 host 固定为 `bemfa.com`，port 固定为 `9501`，用户名密码留空)*

### 方案 B：标准 MQTT (EMQX / Mosquitto) 模式
- **Wi-Fi SSID 与密码**
- **MQTT Broker 地址与端口**（例如 `192.168.1.100` 或域名，端口通常为 `1883`）
- **设备 Client ID**（例如 `esp32_hid_relay_01`）
- **MQTT 用户名与密码**（若 Broker 启用了鉴权）
- **主题名称**：`topic_up` 与 `topic_down`（二者不可相同）

---

## 配网执行方式

### 方式 1：脚本自动化推流配网（首选）

若当前宿主机或操作终端已直连 ESP32 的热点 `ESP32-HID-Setup`（IP 网段为 192.168.4.x）：
```bash
# 巴法云模式
python3 skills/esp32-hid-init/scripts/provision.py \
  --ssid "你的WiFi名称" \
  --wifi-pass "你的WiFi密码" \
  --mqtt-type bemfa \
  --mqtt-client-id "你的巴法云私钥" \
  --topic-up "hidUp001" \
  --topic-down "hidDown001"

# 标准 MQTT 模式
python3 skills/esp32-hid-init/scripts/provision.py \
  --ssid "你的WiFi名称" \
  --wifi-pass "你的WiFi密码" \
  --mqtt-type standard \
  --mqtt-host "192.168.1.100" \
  --mqtt-port 1883 \
  --mqtt-client-id "esp32_hid_relay_01" \
  --mqtt-user "admin" \
  --mqtt-pass "public" \
  --topic-up "esp32/up" \
  --topic-down "esp32/down"
```
脚本会自动探测 `http://192.168.4.1/` 并提交 POST 请求，设备收到后会自动持久化并重启入网。

### 方式 2：手机 / 电脑连接热点配网（图形交互）

若宿主机无法直接切换无线网卡连接热点：
1. **进入配网模式**：设备初次开机（无配置）或运行期间**长按板载 BOOT (GPIO0) 键超过 3 秒**，设备蓝灯闪烁并开启无密码热点 `ESP32-HID-Setup`。
2. **连接热点**：使用手机或电脑 Wi-Fi 搜索并连接 `ESP32-HID-Setup`。
3. **打开配置页**：系统通常会自动弹出强制门户；若未弹出，在浏览器中打开 `http://192.168.4.1/`。
4. **一键填入**：页面提供「巴法云预设」和「标准 MQTT 预设」按钮，填入 SSID、密码、Client ID 及主题后点击「保存并重启」。
5. **生效标志**：ESP32 自动重启并连接目标 Wi-Fi，热点自动关闭，开始监听下行主题并就绪。
