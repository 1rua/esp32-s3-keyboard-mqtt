---
name: esp32-hid-relay
description: ESP32-S3 远程模拟键鼠与 64KB 虚拟 U 盘硬件中转系统的总控技能。帮助用户免去繁琐的手动配置，通过自动化编排三个子阶段（固件编译烧录、硬件初始化配网、Agent端 MCP 配置）并指导 Agent 如何通过 MCP 工具操控目标主机。当用户需要使用此项目、部署 ESP32 硬件代理、通过键鼠与虚拟 U 盘控制远程受控电脑时触发。
---

# ESP32-S3 硬件中转系统自动接入与操控指南

本技能为项目的顶层总控 Skill。目标是**让用户无需手动配置**，只需提供必要的网络与设备信息，Agent 即可全自动完成固件烧录、硬件配网、MCP 接入，并立即进入远程主机操控状态。

---

## 阶段一：收集用户必要配置信息

首先以清晰、通俗的语言向用户确认以下最少必要信息（若用户已在提示词中提供，直接使用并跳过询问）：

1. **硬件连接确认**：
   - 确认 ESP32-S3 开发板已通过 **UART/COM 口** 接入当前电脑（用于烧录）。
   - 确认开发板型号（标准双口 `esp32-s3-devkitc-1`、大内存 `esp32-s3-n16r8`、还是单口小板 `esp32-s3-single-usb`，默认推荐标准双口）。
2. **Wi-Fi 与 MQTT 信息**：
   - **Wi-Fi 名称 (SSID) 与密码**（ESP32 仅支持 2.4GHz Wi-Fi）。
   - **MQTT 服务模式**：
     - **模式 A（巴法云 Bemfa，推荐免自建）**：提供控制台私钥（UID），主题默认自动分配（如 `hidUp001`、`hidDown001`）。
     - **模式 B（标准自建 Broker）**：提供 Broker IP/域名、端口（默认 1883）、用户名与密码（可选）。

---

## 阶段二：自动化编排三步流水线

获取必要信息后，依次调度三个子技能执行全自动化落地：

```
[用户提供必要信息]
        │
        ▼
[步骤 1: 固件编译烧录] (子技能: esp32-hid-flash)
        │
        ▼
[步骤 2: 硬件初始化配网] (子技能: esp32-hid-init)
        │
        ▼
[步骤 3: Agent 端 MCP 配置] (子技能: esp32-hid-mcp-setup)
        │
        ▼
[进入就绪状态: Agent 直接操控受控目标主机]
```

### 步骤 1：固件编译烧录 (`esp32-hid-flash`)
- 调用编译烧录脚本：
  ```bash
  python3 skills/esp32-hid-flash/scripts/flash.py --env <板型> [--port <串口>]
  ```
- 烧录完成后，**明确提示用户**：将开发板的【原生 USB-OTG 接口】插入需要被控的目标主机（电脑），设备将枚举为标准 USB 键鼠与名为 `ESP32_RELAY` 的 64KB 虚拟磁盘。

### 步骤 2：硬件初始化配网 (`esp32-hid-init`)
- 执行配网自动化脚本，将 Wi-Fi 和 MQTT 参数安全写入 ESP32 NVS 闪存：
  ```bash
  python3 skills/esp32-hid-init/scripts/provision.py \
    --ssid "<WiFi名称>" \
    --wifi-pass "<WiFi密码>" \
    --mqtt-type <bemfa|standard> \
    --mqtt-client-id "<私钥或ID>" \
    --topic-up "<上行主题>" \
    --topic-down "<下行主题>"
  ```
- 若宿主机未直连 ESP32 热点，引导用户手机/电脑连接 `ESP32-HID-Setup` 热点完成一键提交。

### 步骤 3：Agent 端 MCP 配置 (`esp32-hid-mcp-setup`)
- 自动准备 Python 运行环境、依赖校验、生成 `agent/.env` 并自测连通性：
  ```bash
  python3 skills/esp32-hid-mcp-setup/scripts/setup_mcp.py \
    --mqtt-type <bemfa|standard> \
    --mqtt-client-id "<私钥或ID>" \
    --topic-up "<上行主题>" \
    --topic-down "<下行主题>"
  ```
- 验证 MCP Server 能正常连接 MQTT Broker，并将配置注册到宿主环境中。

---

## 阶段三：Agent 操控模式（闭环实操手册）

配置完成后，宿主 Agent 拥有专属 MCP 工具，即可直接操控远程目标主机：
- `input_text(text, mode="typing", delay=25, clear_ime=True, target_os="windows")`: **跨设备高阶文本录入工具**。
- `send_hid_commands(commands)`: 细粒度下发按键、输入文本与鼠标移动/点击。
- `read_latest_uplink(timeout)`: 接收受控端写入虚拟 U 盘 `in.txt` 回传的文本。

详细指令语法与各操作系统技巧见参考文档：[`references/agent_control_guide.md`](references/agent_control_guide.md)。

---

### ★★★ 文本录入三大模式与 Agent 自主选择策略 ★★★

为了确保**跨操作系统通用（Windows / Linux / macOS 全支持）**，且满足**“该输入中文时输入中文，该模拟打字时打字”**的要求，Agent 可自行在三大模式中灵活调度：

| 模式名称 | 模式标识 (`mode`) | 特性与底层机制 | 适用场景 |
| :--- | :--- | :--- | :--- |
| **模拟打字模式** | `typing` | **【默认模式】逐键模拟敲击键盘**，纯物理 HID 硬件扫描码。已强化 CRLF 换行归一化（50ms 缓冲）与空格安全隔离时序，打字前自动发 ESC 清理未决拼音悬挂。 | 终端短命令、命令行交互、简单英文 |
| **直接输入文字模式** | `direct` | **直接向活动窗口逐字输入纯 ASCII 文本**，不改变受控端剪贴板。若检测到中文字符，系统自动智能升格为 `paste` 模式避免丢字。 | 纯英文单行代码、不想影响剪贴板时 |
| **粘贴模式** | `paste` | **【该输入中文时输入中文】的通用首选模式**！利用系统剪贴板通道秒级完成粘贴。无论是大段中文、中英混排、多行代码还是特殊符号，100% 保真不丢字、排版不乱、绝不弹拼音。 | 中文段落、中英文注释、多行复杂代码 |

> **⚠️ Agent 核心行为准则（强制遵守）**：
> 1. **默认规则**：如果用户在提示词或任务中**【未明确指定输入模式】**，Agent 必须**默认采用【模拟打字模式 (`typing`)】**执行输入！
> 2. **自主选择策略（该输入中文时输入中文）**：
>    - 当待输入的内容包含**中文字符**（如中文注释、中文文档、汉字提示）、**长篇多行代码**时，由于物理按键只能发送标准 ASCII 扫描码，Agent 必须**主动、自主地选择【粘贴模式 (`paste`)】**，确保中文完整准确上屏！
>    - 当用户需要查看逼真的敲键盘动画、输入终端命令行交互时，Agent 采用【模拟打字模式 (`typing`)】。

---

### 典型操控动作模式

#### 1. 文本输入示例（三大模式自主选择）
```python
# 1. 默认：模拟打字模式（用户未指定模式时必须默认使用）
input_text(text="echo Hello World", mode="typing", delay=25)

# 2. 该输入中文时输入中文：自主选择粘贴模式（中英文混排、多行代码保真粘贴）
input_text(text="// 计算矩阵行列式函数（高斯消元法）\ndouble determinant(int n, const double* matrix) {\n    if (n <= 0) return 0.0;\n    return 1.0;\n}", mode="paste")

# 3. 直接输入文字模式（纯 ASCII 单行代码，不影响系统剪贴板）
input_text(text="int total = 100;", mode="direct")
```

#### 2. Windows 盲操执行命令并捕获回显（带外闭环）
无需受控机连入网络，Agent 下发快捷键执行命令并把结果输出到 U 盘：
```json
[
  {"action": "key", "keys": ["GUI", "R"]},
  {"action": "delay", "ms": 600},
  {"action": "type", "text": "powershell -WindowStyle Hidden -Command \"$d = (Get-Volume -FileSystemLabel 'ESP32_RELAY').DriveLetter; whoami | Out-File -Encoding utf8 ($d + ':\\in.txt')\"", "delay": 20},
  {"action": "delay", "ms": 200},
  {"action": "key", "keys": ["ENTER"]}
]
```
随后调用 `read_latest_uplink(timeout=15)` 读取当前执行用户名。

#### 3. Linux 终端执行命令并回传结果
```json
[
  {"action": "key", "keys": ["CTRL", "ALT", "T"]},
  {"action": "delay", "ms": 1000},
  {"action": "type", "text": "cat /etc/os-release > /media/$USER/ESP32_RELAY/in.txt 2>&1\n", "delay": 20}
]
```
随后调用 `read_latest_uplink(timeout=15)` 读取发行版信息。

#### 4. 鼠标交互与图形界面点击
```json
[
  {"action": "mouse_move", "x": 150, "y": 80},
  {"action": "delay", "ms": 100},
  {"action": "mouse_click", "button": "left", "double": false}
]
```
