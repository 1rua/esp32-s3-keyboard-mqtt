# Agent 操控受控目标主机实战指南 (Agent Control Guide)

通过 ESP32-S3 模拟的 USB HID 键鼠与 64KB FAT12 虚拟 U 盘，Agent 具备了**硬件级带外操控能力**：无需目标主机连入互联网、无需安装任何被控端软件，只要目标主机插入了开发板的原生 USB-OTG 接口，Agent 即可进行完全解耦的键鼠输入与回显数据读取。

---

## 一、MCP 工具接口定义

MCP Server (`esp32-hid-relay`) 暴露了两个基础工具：

### 1. `send_hid_commands(commands: list[dict])`
向下行主题发送 JSON 指令队列。数组中的所有动作会按顺序在 ESP32 上执行。

支持的动作类型：
- **文本输入 (`type`)**：
  `{"action": "type", "text": "cmd.exe", "delay": 20}`
  - `text`: 待输入的纯文本（仅支持标准 ASCII 字符，输入换行请用 `\n`）。
  - `delay`: 字符间输入延时（毫秒，默认 20ms，防止受控端丢字；输入长命令建议 15~30ms）。
- **按键/快捷键 (`key`)**：
  `{"action": "key", "keys": ["GUI", "R"]}`
  - `keys`: 按键标记列表。列表内多个键会同时按下并自动释放。
  - 常用修饰键：`CTRL`, `ALT`, `SHIFT`, `GUI` (Win/Cmd键)。
  - 常用控制键：`ENTER`, `TAB`, `ESC`, `BACKSPACE`, `SPACE`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `PAGEUP`, `PAGEDOWN`, `F1`~`F12`。
- **鼠标相对移动 (`mouse_move`)**：
  `{"action": "mouse_move", "x": 100, "y": -50}`
  - `x`: X 轴相对位移（向右为正，向左为负）。
  - `y`: Y 轴相对位移（向下为正，向上为负）。
  - 固件已内置超限自动分片，单次传大数值（如 `x: 800`）亦可平滑分步移动。
- **鼠标点击 (`mouse_click`)**：
  `{"action": "mouse_click", "button": "left", "double": false}`
  - `button`: `left` (左键), `right` (右键), `middle` (中键)。
  - `double`: `true` 为双击，`false` 为单击。
- **延时等待 (`delay`)**：
  `{"action": "delay", "ms": 500}`
  - `ms`: 等待毫秒数（上限 30000ms），用于等待目标系统弹窗或应用加载。

### 2. `read_latest_uplink(timeout: int = 10) -> str`
阻塞等待并返回 ESP32 虚拟 U 盘抓取到的最新一条文件内容（来自目标主机向虚拟盘 `in.txt` 的写入）。
- `timeout`: 最长等待秒数（默认 10 秒，最大 300 秒）。
- 若超时未收到任何内容，返回空字符串 `""`。

---

## 二、核心工作流：带外闭环命令执行模式

利用虚拟 U 盘（卷标 `ESP32_RELAY`，容量 64KB），Agent 可以下发运行命令，受控主机将执行结果写入 U 盘根目录的 `in.txt`，ESP32 内部防抖 1000ms 后解析并将内容推回 MQTT，Agent 随后调用 `read_latest_uplink` 获取输出，完成**双向命令闭环**。

### 模式 A：Windows 受控主机闭环执行

#### 1. 打开运行窗口并静默执行命令
通过 `Win + R` 唤起运行框，使用 powershell 执行目标命令并将输出重定向至虚拟 U 盘 `in.txt`。

```json
[
  {"action": "key", "keys": ["GUI", "R"]},
  {"action": "delay", "ms": 600},
  {"action": "type", "text": "powershell -WindowStyle Hidden -Command \"$drive = (Get-Volume -FileSystemLabel 'ESP32_RELAY').DriveLetter; ipconfig | Out-File -Encoding utf8 -FilePath ($drive + ':\\in.txt')\"", "delay": 15},
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

## 三、常用场景指令示例库

### 场景 1：Windows 锁屏解锁与密码输入
```json
[
  {"action": "key", "keys": ["SPACE"]},
  {"action": "delay", "ms": 500},
  {"action": "type", "text": "MyPassword123", "delay": 30},
  {"action": "delay", "ms": 200},
  {"action": "key", "keys": ["ENTER"]}
]
```

### 场景 2：打开浏览器访问特定网页
```json
[
  {"action": "key", "keys": ["GUI", "R"]},
  {"action": "delay", "ms": 500},
  {"action": "type", "text": "msedge https://www.bing.com", "delay": 15},
  {"action": "delay", "ms": 200},
  {"action": "key", "keys": ["ENTER"]}
]
```

### 场景 3：输入大段脚本或绕过特殊字符
USB HID 键盘只能逐键敲击 ASCII 字符，若需要向受控机传输包含特殊符号、多行脚本或中文字符的复杂内容，最佳实践是：
1. **Base64 编码传输**：
   将脚本编码为 Base64 单行文本，在目标主机通过 `[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('...'))` 解码后执行。
2. **通过虚拟 U 盘中转**：受控机也可以直接运行脚本并将详细报错或日志重定向回 `in.txt`。

---

## 四、Agent 交互注意事项

1. **操作前防丢步**：下发弹窗类按键（如 `GUI + R` 或 `CTRL + ALT + T`）后，**务必附加 500~1000ms 的 `delay`**，等待受控机 UI 绘制完成再输入后续文本。
2. **虚拟盘写入防抖机制**：受控端写入 `in.txt` 后，ESP32 固件有 1000ms 的防抖等待以确保受控端刷盘结束，读取上行时建议将 `timeout` 设置在 10~20 秒以上。
3. **单包体积注意**：受限于 64KB FAT12 格式与 MQTT 单包缓冲区（8KB），单次写入 `in.txt` 的文本内容建议控制在 8KB 以内。长输出建议使用 `head -n 50` 或分页截断。
