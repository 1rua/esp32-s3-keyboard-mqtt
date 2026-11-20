# Agent 操控受控目标主机实战指南 (Agent Control Guide)

通过 ESP32-S3 模拟的 USB HID 键鼠与 64KB FAT12 虚拟 U 盘，Agent 具备了**硬件级带外操控能力**：无需目标主机连入互联网、无需安装任何被控端软件，只要目标主机插入了开发板的原生 USB-OTG 接口，Agent 即可进行完全解耦的键鼠输入与回显数据读取。

---

## 一、MCP 工具接口定义

MCP Server (`esp32-hid-relay`) 暴露了核心工具：

### 1. `input_text(text: str, mode: str = "typing", delay: int = 25, clear_ime: bool = True, target_os: str = "windows")`
专用于文本录入的高阶工具，提供三种模式以应对各种跨设备输入场景：

> **⚠️ 核心准则**：
> 1. **默认策略**：**如果用户没有明确指定输入模式，Agent 必须默认使用 `typing`（模拟打字模式）！**
> 2. **自主决策（该输入中文时输入中文）**：**凡文本中包含中文汉字、中文注释、多行复杂代码，Agent 应主动、自主地选择 `paste`（粘贴模式），以确保中文字符 100% 完整录入且排版完全保真。**

| 模式 | 参数值 | 说明与工作机制 | 适用场景与限制 |
| :--- | :--- | :--- | :--- |
| **模拟打字模式** | `"typing"` | **【默认】逐键模拟敲击物理键盘**，按 `delay` 间隔逐字敲入。纯硬件扫描码实现，跨 Windows / Linux / macOS 通用。打字前自动发 ESC 清理未决拼音悬挂，已针对换行与空格时序防抖加固。 | 终端命令、命令行交互、纯 ASCII 短文本 |
| **直接输入文字模式** | `"direct"` | **直接向当前活动窗口逐字输入纯 ASCII 文本**，不经过系统剪贴板。若检测到中文字符，自动安全升格为 `paste` 模式防丢字。 | 纯英文单行代码、不想覆盖剪贴板时 |
| **粘贴模式** | `"paste"` | **【该输入中文时输入中文】的通用首选模式**！利用受控机系统剪贴板通道秒级完成粘贴。输入大段中文、中英文注释、复杂多行源码时的唯一绝对保真模式。 | 多行源码、中英文混合、中文注释、长文本 |

### 2. `send_hid_commands(commands: list[dict])`
向下行主题发送 JSON 指令队列。数组中的所有动作会按顺序在 ESP32 上执行。

支持的动作类型：
- **模拟打字 (`type`)**：
  `{"action": "type", "text": "echo hello", "delay": 25, "clear_ime": true}`
- **直接输入文字 (`direct_text`)**：
  `{"action": "direct_text", "text": "var x = 1;", "delay": 25}`
- **粘贴模式 (`paste`)**：
  - 自动安全置剪贴板并粘贴：`{"action": "paste", "text": "#include <stdio.h>\n...", "target_os": "windows"}`
  - 纯物理按键粘贴：`{"action": "paste"}`（触发 Ctrl + V，macOS 自动适配 Cmd + V）
- **按键/快捷键 (`key`)**：
  `{"action": "key", "keys": ["GUI", "R"]}`
  - 常用修饰键：`CTRL`, `ALT`, `SHIFT`, `GUI` (Win/Cmd键)。
  - 常用控制键：`ENTER`, `TAB`, `ESC`, `BACKSPACE`, `SPACE`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `PAGEUP`, `PAGEDOWN`, `F1`~`F12`。
- **鼠标相对移动 (`mouse_move`)**：
  `{"action": "mouse_move", "x": 100, "y": -50}`
- **鼠标点击 (`mouse_click`)**：
  `{"action": "mouse_click", "button": "left", "double": false}`
- **延时等待 (`delay`)**：
  `{"action": "delay", "ms": 500}`

### 3. `read_latest_uplink(timeout: int = 10) -> str`
阻塞等待并返回 ESP32 虚拟 U 盘抓取到的最新一条文件内容（来自目标主机向虚拟盘 `in.txt` 的写入）。

---

## 二、连续中英文输入错乱的原因与三大模式的解决方案

### 1. 为什么模拟键盘输入连续中英文/代码时会错乱？
在目标主机处于中文输入法状态下（如微软拼音、搜狗输入法、Fcitx5 等），当逐键模拟敲击英文字母时：
1. 英文字母会被操作系统输入法拦截并作为拼音缓冲；
2. 当遇到空格 `' '` 时，输入法会将空格作为“确认首选候选词”提交上屏，导致英文字母被强行转变为风马牛不相及的中文词汇（例如 `stdio` 遇到空格变成“收徒弟哦”，`double` 变成“的特人民安踏”）；
3. 当遇到回车 `\n` 时，若未做防抖或时序隔离，可能触发输入法编码直接上屏或连续换行错位；
4. 符号键（如 `<`、`>`、`#`）需要触发 Shift 键，若按键抬起过快，可能被系统误判为单击 Shift 从而反复切换中英文状态；
5. USB HID 物理键盘只能模拟标准 ASCII 扫描码，无法直接敲击中文字符，若强行打字，中文字符会被丢弃。

### 2. 解决方案与选择指引
- **默认选择（模拟打字模式）**：
  打字前自动发送 `ESC` 清除历史拼音悬挂，按键保持时间（10ms）与换行隔离延时（50ms）有效消除了物理层粘连。若用户未特别指定模式，**一律默认采用此模式**。
- **大段代码/中英文混排强烈推荐（粘贴模式）**：
  用户若要求输入整段代码、多行配置或包含中英文的复杂文档，使用 `mode="paste"`。粘贴模式彻底绕过输入法的所有按键拦截，无论多长均可瞬间无损完成录入，且排版与中文 100% 完整。
- **纯英文免剪贴板场景（直接输入模式）**：
  若输入纯英文内容且用户明确要求不覆盖原有剪贴板，使用 `mode="direct"`。若包含中文，系统会自动安全升格为 `paste` 模式避免丢字。

---

## 三、核心工作流：带外闭环命令执行模式

利用虚拟 U 盘（卷标 `ESP32_RELAY`，容量 64KB），Agent 可以下发运行命令，受控主机将执行结果写入 U 盘根目录的 `in.txt`，ESP32 内部防抖 1000ms 后解析并将内容推回 MQTT，Agent 随后调用 `read_latest_uplink` 获取输出，完成**双向命令闭环**。

### 模式 A：Windows 受控主机闭环执行

#### 1. 打开运行窗口并静默执行命令
通过 `Win + R` 唤起运行框，使用 powershell 执行目标命令并将输出重定向至虚拟 U 盘 `in.txt`。

```json
[
  {"action": "key", "keys": ["GUI", "R"]},
  {"action": "delay", "ms": 600},
  {"action": "type", "text": "powershell -WindowStyle Hidden -Command \"$d = (Get-Volume -FileSystemLabel 'ESP32_RELAY').DriveLetter; whoami | Out-File -Encoding utf8 ($d + ':\\in.txt')\"", "delay": 20},
  {"action": "delay", "ms": 200},
  {"action": "key", "keys": ["ENTER"]}
]
```

#### 2. 读取回显输出
Agent 紧接着调用：
```python
read_latest_uplink(timeout=15)
```
即可拿到受控机执行 `ipconfig` 的完整网络配置文本！

---

### 模式 B：Linux 受控主机闭环执行

#### 1. 快捷键唤出终端并执行
```json
[
  {"action": "key", "keys": ["CTRL", "ALT", "T"]},
  {"action": "delay", "ms": 1000},
  {"action": "type", "text": "uname -a > /media/$USER/ESP32_RELAY/in.txt 2>&1\n", "delay": 20}
]
```

#### 2. 读取回显输出
Agent 调用 `read_latest_uplink(timeout=10)` 获取系统内核信息。

---

## 四、Agent 交互注意事项

1. **用户未指定输入模式时，默认使用模拟打字模式 (`typing`)**。
2. **该输入中文时输入中文**：涉及中文（文档、注释、汉字）或多行代码时，Agent 必须自主选用 `paste` 模式以确保字符完整。
3. **操作前防丢步**：下发弹窗类按键（如 `GUI + R` 或 `CTRL + ALT + T`）后，务必附加 500~600ms 的 `delay`，等待受控机 UI 绘制完成再输入后续文本。
