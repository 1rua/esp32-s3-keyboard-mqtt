# ESP32-S3 远程键鼠模拟与虚拟 U 盘中转系统

通过 ESP32-S3 硬件将 AI Agent 与目标主机连接。下行通过 MQTT 接收控制指令，模拟标准 USB 键盘与鼠标；上行通过 64KB 虚拟 U 盘接收目标主机写入的文件，实现带外命令执行与双向数据闭环。

---

## 硬件接口与接线说明（重要）

标准 ESP32-S3 开发板通常配备两个 Type-C 接口，请务必注意区分：

- **UART / COM 口**：仅用于连接开发电脑进行固件编译烧录，以及查看串口调试日志（115200 波特率）。
- **USB-OTG 原生口**：**必须连接受控目标主机**。该接口由 ESP32-S3 片上原生 USB 控制器直接驱动，负责枚举为 HID 键盘、HID 鼠标以及卷标为 `ESP32_RELAY` 的虚拟 U 盘。若误插至 UART 口，受控主机将无法识别任何键鼠或存储设备。

---

## 快速开始

### 方式一：一句话 Skill 自动化配置（推荐）

本项目内置了完整的 Agent 自动化执行能力（位于 `skills/` 目录）。你无需手动执行编译、烧录和配置，只需让支持 Skill 的 Agent（如 DSH、Claude Desktop、Cursor 等）加载主技能并告知必要参数即可：

> **一句话提示词示例**：  
> “请使用当前项目的 `esp32-hid-relay` 技能帮我配置硬件并开始操控。我的 Wi-Fi 是 `Office_WiFi`，密码是 `12345678`，巴法云私钥是 `xxxxxxxx`，开发板已通过 UART 口连接电脑。”

Agent 将依次自动完成以下步骤：
1. **自动编译与烧录**：调用 `esp32-hid-flash` 编译固件并刷入连接的 ESP32-S3 开发板；
2. **自动配网与初始化**：调用 `esp32-hid-init` 向设备写入 Wi-Fi 与 MQTT 参数并持久化至 NVS；
3. **自动配置 MCP 环境**：调用 `esp32-hid-mcp-setup` 准备本地 Python 依赖、写入环境变量并完成连通性测试；
4. **提示切换硬件接口**：提醒你将开发板的 **USB-OTG 原生口** 接入受控目标机；
5. **直接进入操控模式**：Agent 调用 `send_hid_commands` 与 `read_latest_uplink` 开始控制目标主机。

---

### 方式二：手动配置

若需手动编译烧录与部署，请按以下步骤操作：

#### 1. 固件编译与烧录
1. 使用 USB 数据线连接开发板的 **UART 口** 至本地电脑。
2. 安装 PlatformIO 核心工具后，在项目根目录执行：
   ```bash
   # 标准 ESP32-S3-DevKitC-1 开发板
   pio run -e esp32-s3-devkitc-1 -t upload
   ```
   *(注：若使用 16MB Flash 开发板可指定 `-e esp32-s3-n16r8`；单口板指定 `-e esp32-s3-single-usb`)*

#### 2. 设备动态配网
1. 烧录完成后，开发板首次通电（或长按板载 `BOOT (GPIO0)` 键超过 3 秒），将开启无密码 Wi-Fi 热点 `ESP32-HID-Setup`。
2. 使用手机或电脑连接该热点，在弹出的页面（或浏览器访问 `http://192.168.4.1/`）填写：
   - Wi-Fi 名称与密码；
   - MQTT Broker 信息：巴法云填写 `bemfa.com:9501` 与控制台私钥；自建 Broker 填写对应 IP、端口及账密；
   - 上行主题（如 `hidUp001`）与下行主题（如 `hidDown001`）。
3. 点击「保存并重启」，ESP32 将自动连接目标 Wi-Fi 并接入 MQTT 服务。

#### 3. 硬件接线切换
将开发板与开发电脑断开，使用 USB 线将其 **USB-OTG 原生口** 插入需要被控制的目标电脑。目标电脑将自动识别出 HID 键鼠设备与一个 64KB 的磁盘。

#### 4. Agent 端 MCP 服务接入
1. 进入 `agent/` 目录准备 Python 环境并安装依赖：
   ```bash
   cd agent
   python3 -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. 复制配置模板并填入与设备一致的 MQTT 参数：
   ```bash
   cp .env.example .env
   ```
   *(注意：若使用标准 MQTT Broker，Agent 端的 Client ID 必须与 ESP32 设备的 Client ID 不同，例如附加 `_agent` 后缀，避免 Broker 互踢断线)*
3. 在 MCP 宿主（如 Claude Desktop 的 `claude_desktop_config.json` 或 Cursor）中添加服务配置：
   ```json
   {
     "mcpServers": {
       "esp32-hid-relay": {
         "command": "/绝对路径/agent/.venv/bin/python",
         "args": ["/绝对路径/agent/mqtt_mcp_server.py"]
       }
     }
   }
   ```

---

## 开发文档

### 系统架构

```text
┌────────────────────────────┐          ┌───────────────────────────────┐
│     AI Agent / MCP 宿主    │          │       受控目标主机 (PC)       │
│  (Claude Desktop / Cursor) │          │  (无须联网 / 支持锁屏与隔离)  │
└─────────────┬──────────────┘          └───────▲───────────────┬───────┘
              │ stdio MCP                       │ USB HID       │ 写入 E:\in.txt
┌─────────────▼──────────────┐                  │ (键鼠控制)    │ (64KB FAT12 MSC)
│  agent/mqtt_mcp_server.py  │                  │               ▼
│  - send_hid_commands()     │          ┌───────┴───────────────────────┐
│  - read_latest_uplink()    │          │    ESP32-S3 (原生 USB-OTG)    │
│  agent/mqtt_watcher.py     │          │  - USBHIDKeyboard + Mouse     │
└──────┬────────────▲────────┘          │  - 64KB FAT12 RAM Disk        │
       │            │                   │  - 1000ms 防抖 & USB 软重连   │
       │ Publish    │ Subscribe         │  - NVS 持久化 + 动态配网      │
       │ topic_down │ topic_up          └───────▲───────────────┬───────┘
       ▼            │                           │ Subscribe     │ Publish
┌───────────────────┴───────────────────────────┴───────────────▼───────┐
│           MQTT Broker (巴法云 bemfa.com:9501 / EMQX / Mosquitto)      │
└───────────────────────────────────────────────────────────────────────┘
```

---

### 下行键鼠控制协议 (`topic_down`)

MCP 工具 `send_hid_commands(commands)` 接收一个 JSON 数组或单条 JSON 对象，指令按序执行：

- **输入纯文本 (`type`)**：
  ```json
  {"action": "type", "text": "echo hello", "delay": 20}
  ```
  逐字符模拟键盘敲击输入标准 ASCII 文本。`delay` 为字符间间隔（毫秒），建议设为 15~30ms 防止丢键。
- **按键与组合快捷键 (`key`)**：
  ```json
  {"action": "key", "keys": ["GUI", "R"]}
  {"action": "key", "keys": ["CTRL", "C"]}
  {"action": "key", "keys": ["ENTER"]}
  ```
  支持的修饰键包括 `CTRL`, `ALT`, `SHIFT`, `GUI` (Win/Cmd 键)；支持常用控制键如 `ENTER`, `TAB`, `ESC`, `BACKSPACE`, `SPACE`, 方向键及 `F1`~`F12`。
- **鼠标相对位移 (`mouse_move`)**：
  ```json
  {"action": "mouse_move", "x": 100, "y": -50}
  ```
  控制光标相对当前位置移动，固件自动将大数值分片为平滑运动。
- **鼠标点击 (`mouse_click`)**：
  ```json
  {"action": "mouse_click", "button": "left", "double": false}
  ```
  `button` 可选 `left`, `right`, `middle`；`double` 为 `true` 时执行双击。
- **动作延时 (`delay`)**：
  ```json
  {"action": "delay", "ms": 500}
  ```
  用于等待受控端系统窗口弹出或界面响应。

---

### 上行传输机制 (`topic_up`)

受控目标机写入文件后回传数据的完整机制：
1. **虚拟磁盘构造**：ESP32 内部内存构建标准的 64KB FAT12 格式磁盘，预置单个空文件 `in.txt`。
2. **写入与防抖**：目标主机向虚拟盘的 `in.txt` 写入内容。ESP32 检测到底层扇区写操作后启动 1000ms 防抖定时器，确保操作系统刷盘完成。
3. **提取与上报**：防抖结束后遍历 FAT 簇链读取非空 UTF-8 文本，发布至 MQTT 的 `topic_up`。
4. **软重连刷新**：上报成功后自动重置虚拟盘，并调用 USB 软重连（`tud_disconnect` → 延时 300ms → `tud_connect`），强制受控操作系统刷新磁盘缓存，为下次写入做好准备。
5. **Agent 读取**：Agent 端调用 `read_latest_uplink(timeout=10)` 阻塞接收最新上报的文本。

---

### 双向带外闭环交互示例

无需受控机连入网络，Agent 可通过盲打执行系统命令并将结果写入虚拟盘回传：

#### Windows 示例：静默执行命令并读取回显
```json
// Agent 下发按键指令
[
  {"action": "key", "keys": ["GUI", "R"]},
  {"action": "delay", "ms": 600},
  {"action": "type", "text": "powershell -WindowStyle Hidden -Command \"$d = (Get-Volume -FileSystemLabel 'ESP32_RELAY').DriveLetter; whoami | Out-File -Encoding utf8 ($d + ':\\in.txt')\"", "delay": 20},
  {"action": "delay", "ms": 200},
  {"action": "key", "keys": ["ENTER"]}
]
```
下发完成后调用 `read_latest_uplink(timeout=15)`，即可获取受控机的命令输出。

---

### 项目代码结构

```text
esp32-s3-hid-msc-mqtt/
├── platformio.ini                # 固件编译环境与依赖定义
├── include/                      # 固件头文件
│   ├── config_store.h            # NVS 配置读写
│   ├── captive_portal.h          # 强制门户配网
│   ├── ram_disk.h                # 64KB FAT12 内存盘与防抖解析
│   ├── hid_executor.h            # HID 键鼠执行器
│   └── mqtt_bridge.h             # MQTT 通信与断线重连
├── src/                          # 固件实现源码
├── agent/                        # Agent 端组件
│   ├── requirements.txt          # Python 依赖
│   ├── .env.example              # 环境变量模板
│   ├── mqtt_mcp_server.py        # 通用 FastMCP 服务端
│   └── mqtt_watcher.py           # 上行监听与 Webhook 回调守护
└── skills/                       # 内置 Agent Skills 套件
    ├── esp32-hid-relay/          # 主技能（总调度与实战指南）
    ├── esp32-hid-flash/          # 子技能 1（固件自动编译与烧录）
    ├── esp32-hid-init/           # 子技能 2（设备初始化与网络配置）
    └── esp32-hid-mcp-setup/      # 子技能 3（Agent 运行环境与 MCP 配置）
```

---

### 常见问题与排查

1. **目标主机无法识别键鼠或 U 盘**：
   - 检查线缆是否插入了开发板的 **USB-OTG 原生口**。若插在 UART 口，目标机仅能识别为串口设备。
   - 确认 USB 线支持数据传输，排除仅充电线缆。
2. **MQTT 频繁掉线互踢**：
   - 在标准 MQTT Broker（如 EMQX / Mosquitto）中，确保 ESP32 与 Agent 端的 `MQTT_CLIENT_ID` 不相同。
3. **中文输入**：
   - USB HID 模拟的是标准物理键盘按键扫描码，不能直接敲出中文字符。如需输入中文，建议通过剪贴板粘贴或命令重定向写入。
4. **重新进入配网模式**：
   - 通电运行期间，长按开发板上的 `BOOT (GPIO0)` 键超过 3 秒，设备将再次开启 `ESP32-HID-Setup` 配网热点。
