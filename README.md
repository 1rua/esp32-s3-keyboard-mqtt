# ESP32-S3 远程模拟键鼠 + 64KB 虚拟 U 盘中转系统

一套**上下行完全解耦、零硬编码、支持 WebUI 强制门户动态配网**的硬件代理中转方案，包含 **ESP32-S3 固件（PlatformIO + Arduino + TinyUSB）** 与 **Agent 端通用 MQTT MCP Server（Python FastMCP + paho-mqtt）** 两大部分。

---

## 核心特性

- **上下行严格解耦**：上行（虚拟 U 盘回传文本）与下行（远程键鼠指令）使用独立 MQTT 主题，互不阻塞；即使受控主机界面锁死或处于全屏受限环境，下行 HID 盲操仍可独立执行。
- **零硬编码动态配网（AP + Captive Portal + NVS）**：所有 Wi-Fi 与 MQTT 参数持久化保存在 ESP32 NVS（`Preferences`）中。首次开机无配置，或开机/运行期间长按板载 `BOOT (GPIO0)` 键超过 3 秒，自动开启 `ESP32-HID-Setup` 热点并通过 `DNSServer` + `WebServer` 弹出极简内联配置页（零外部 CDN 依赖），同时兼容**巴法云（无账密）**与**标准 EMQX / Mosquitto（账密认证）**。
- **TinyUSB 三合一复合设备**：单根 USB 线缆同时枚举 `USBHIDKeyboard`、`USBHIDMouse` 与 `USBMSC`（大容量存储），无需外置 SD 卡。
- **64KB FAT12 内存盘 + 1000ms 防抖 + 软重连刷新**：在内部 RAM 中构造标准 64KB FAT12 磁盘并预置 `in.txt`；主机写入后触发 1000ms 防抖，遍历 FAT12 簇链提取非空文本并发布至 `topic_up`，成功后立即重置内存盘并执行 `tud_disconnect()` → `delay(300)` → `tud_connect()` 强制主机刷新文件缓存。
- **通用 Agent MCP 接入与守护监听**：Python 端全部通过环境变量读取配置，提供 `send_hid_commands` / `read_latest_uplink` MCP 工具以及独立守护脚本 `mqtt_watcher.py`（内置 Webhook 回调钩子）。

---

## 系统架构

```text
┌────────────────────────────┐          ┌───────────────────────────────┐
│     AI Agent / MCP 宿主    │          │       受控目标主机 (PC)       │
│  (Claude Desktop / Cursor) │          │  (支持网络隔离 / 锁屏盲操)    │
└─────────────┬──────────────┘          └───────▲───────────────┬───────┘
              │ stdio MCP                       │ USB HID       │ 写入 E:\in.txt
┌─────────────▼──────────────┐                  │ (键鼠控制)    │ (64KB FAT12 MSC)
│  agent/mqtt_mcp_server.py  │                  │               ▼
│  - send_hid_commands()     │          ┌───────┴───────────────────────┐
│  - read_latest_uplink()    │          │    ESP32-S3 (原生 USB-OTG)    │
│  agent/mqtt_watcher.py     │          │  - USBHIDKeyboard + Mouse     │
└──────┬────────────▲────────┘          │  - 64KB FAT12 RAM Disk        │
       │            │                   │  - 1000ms 防抖 & USB 软重连   │
       │ Publish    │ Subscribe         │  - NVS + AP Captive Portal    │
       │ topic_down │ topic_up          └───────▲───────────────┬───────┘
       ▼            │                           │ Subscribe     │ Publish
┌───────────────────┴───────────────────────────┴───────────────▼───────┐
│           MQTT Broker（巴法云 bemfa.com:9501 / EMQX / Mosquitto）     │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 项目目录结构

```text
esp32-s3-hid-msc-mqtt/
├── firmware/
│   ├── platformio.ini            # ESP32-S3 TinyUSB 复合设备编译配置与依赖
│   ├── include/
│   │   ├── config_store.h        # NVS Preferences 配置结构体与读写接口
│   │   ├── captive_portal.h      # SoftAP + DNSServer + WebServer 强制门户声明
│   │   ├── ram_disk.h            # 64KB FAT12 虚拟内存盘与 1000ms 防抖接口
│   │   ├── hid_executor.h        # USB HID 键鼠 JSON 指令执行器声明
│   │   └── mqtt_bridge.h         # Wi-Fi / MQTT 自动重连与下行队列声明
│   └── src/
│       ├── main.cpp              # 启动校验、GPIO0 (BOOT) 长按 3s 检测与主循环
│       ├── config_store.cpp      # NVS 持久化读写与清空实现
│       ├── captive_portal.cpp    # 零外部 CDN 内联 HTML/CSS 配网门户实现
│       ├── ram_disk.cpp          # FAT12 构造/簇链解析 + tud_disconnect/connect 重连
│       ├── hid_executor.cpp      # 单条/批量 JSON 指令、组合键映射与鼠标 int8 分片
│       └── mqtt_bridge.cpp       # 巴法云无账密 / EMQX 账密自适应连接与断线重连
├── agent/
│   ├── requirements.txt          # Python 依赖（fastmcp, paho-mqtt, python-dotenv）
│   ├── .env.example              # Agent 端环境变量模板
│   ├── mqtt_mcp_server.py        # 通用 MQTT MCP Server
│   └── mqtt_watcher.py           # 上行监听守护脚本 + Agent Webhook 回调模板
└── README.md                     # 本说明文档
```

---

## 硬件准备与接线说明

- **推荐开发板**：带有原生 USB-OTG 接口的 **ESP32-S3** 开发板（如 `ESP32-S3-DevKitC-1`，通常配备 `UART/COM` 与 `USB/OTG` 两个 Type-C 接口）。
- **双口用途区分**：
  1. **UART / COM 口**：用于 PlatformIO 编译烧录及 115200 波特率串口日志监控（因 `-DARDUINO_USB_CDC_ON_BOOT=0`，日志默认走 UART0）。
  2. **USB / OTG 原生口**：接入需要受控的目标主机，枚举为 HID 键盘 + HID 鼠标 + 卷标 `ESP32_RELAY` 的 64KB 虚拟 U 盘。
- **板载 `BOOT` 按钮（GPIO0）**：开机时或运行期间长按超过 **3 秒** 进入强制门户配网模式。

---

## 一、ESP32-S3 固件编译与烧录

1. 安装 VS Code + PlatformIO IDE（或 CLI `pip install platformio`）。
2. `firmware/platformio.ini` 自动拉取 `PubSubClient@^2.8` 与 `ArduinoJson@^7.2.0`；关键编译标志：
   - `-DARDUINO_USB_MODE=0`：启用 TinyUSB 原生 USB-OTG。
   - `-DARDUINO_USB_CDC_ON_BOOT=0`：保持 USB 描述符纯净，调试日志走 UART0。
   - `-DMQTT_MAX_PACKET_SIZE=8192`：支持大段上行文本与批量 HID JSON 队列。
3. 将开发板 **UART 口** 连接电脑后执行：
   ```bash
   cd firmware
   pio run -t upload
   pio device monitor -b 115200
   ```
4. 烧录完成后，将 **USB-OTG 原生口** 插入受控目标主机。

---

## 二、WebUI 强制门户动态配网

1. 首次通电（NVS 无有效配置）或长按 `BOOT (GPIO0)` > 3 秒后，设备开启开放热点 `ESP32-HID-Setup`。
2. 手机或电脑连接热点后自动弹出配网页（或手动访问 `http://192.168.4.1/`）。
3. 参数对照：
   - **巴法云 (Bemfa)**：`mqtt_host = bemfa.com`，`mqtt_port = 9501`，`mqtt_client_id` 填私钥，`mqtt_user / mqtt_pass` **留空**。
   - **标准 MQTT (EMQX / Mosquitto)**：填 Broker IP/域名与端口 `1883`，设备与 Agent 使用不同 `Client ID`，按需填账密。
4. 配置不同的 `topic_up` 与 `topic_down`，点击「保存并重启」。

---

## 三、下行键鼠控制协议（`topic_down`）

支持单条 JSON 对象或 JSON 数组批量执行：
- `{"action":"type","text":"hello","delay":20}`：逐字符输入 ASCII 文本，可配置间隔（ms）防丢字。
- `{"action":"key","keys":["CTRL","C"]}`：单键或组合快捷键（支持 `CTRL/ALT/SHIFT/GUI/ENTER/TAB/ESC/F1-F12` 等）。
- `{"action":"mouse_move","x":160,"y":-45}`：相对位移，超出 `[-127, 127]` 自动分片。
- `{"action":"mouse_click","button":"left","double":false}`：支持 `left / right / middle` 及双击。
- `{"action":"delay","ms":500}`：分片延时（上限 30000ms），不触发看门狗。

---

## 四、上行 64KB FAT12 虚拟 U 盘机制（`topic_up`）

- **扇区布局**：Sector 0 (BPB) + Sector 1–2 (双 FAT12) + Sector 3 (根目录含 `IN.TXT`) + Sector 4–127 (124 个数据簇，约 62KB 可用)。
- **上传与刷新**：主机写入 `in.txt` → 1000ms 防抖 → 遍历簇链提取并去 BOM/空白 → 发布 `topic_up` → 清空重置内存盘 → `tud_disconnect()` + `delay(300)` + `tud_connect()` 强制主机刷新缓存。

---

## 五、Agent 端 Python 组件启动与 MCP 接入

```bash
cd agent
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # 填入与设备一致的 MQTT 参数
python mqtt_watcher.py           # 启动上行监听守护（可配 AGENT_WEBHOOK_URL）
```

MCP 客户端（Claude Desktop / Cursor 等）配置示例：

```json
{
  "mcpServers": {
    "esp32-hid-relay": {
      "command": "python",
      "args": ["/abs/path/to/esp32-s3-hid-msc-mqtt/agent/mqtt_mcp_server.py"],
      "env": {
        "MQTT_HOST": "bemfa.com",
        "MQTT_PORT": "9501",
        "MQTT_CLIENT_ID": "YOUR_CLIENT_ID",
        "MQTT_USER": "",
        "MQTT_PASS": "",
        "MQTT_TOPIC_UP": "hidUp004",
        "MQTT_TOPIC_DOWN": "hidDown004"
      }
    }
  }
}
```

---

## 六、常见问题排查（FAQ）

1. **未识别虚拟 U 盘/键鼠**：确认插在开发板的 **USB-OTG 原生口** 而非 UART 口，且线缆支持数据传输。
2. **标准 Broker 频繁互踢掉线**：EMQX / Mosquitto 下请为 ESP32、`mqtt_mcp_server.py` 与 `mqtt_watcher.py` 分配不同的 `Client ID`。
3. **超长文本上传**：若需单次超过 8KB，请同步调大 `MQTT_MAX_PACKET_SIZE` 与 `gMqtt.setBufferSize()`，并确认 Broker 单包限制。
4. **安全建议**：勿将包含私钥或密码的 `.env` 提交至代码仓库，生产环境建议使用带 ACL 鉴权的私有 Broker。
