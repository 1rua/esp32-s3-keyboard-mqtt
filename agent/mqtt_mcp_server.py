"""
通用 MQTT MCP Server (ESP32-S3 HID Relay & Virtual MSC 配套组件)

依赖：fastmcp, paho-mqtt, python-dotenv
环境变量：
  MQTT_HOST       - MQTT Broker 主机名或 IP（必填）
  MQTT_PORT       - MQTT 端口（默认 1883，巴法云 9501）
  MQTT_CLIENT_ID  - MQTT Client ID（巴法云填私钥）
  MQTT_USER       - 可选用户名（留空采用无账密连接）
  MQTT_PASS       - 可选密码
  MQTT_TOPIC_UP   - 上行主题（订阅 ESP32 虚拟 U 盘回传文本）
  MQTT_TOPIC_DOWN - 下行主题（向 ESP32 发送 JSON 键鼠指令）
"""

from __future__ import annotations

import base64
import json
import os
import queue
import threading
import time
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP
import paho.mqtt.client as mqtt

# 自动加载当前目录与脚本所在目录的 .env（若存在），不覆盖系统已注入的环境变量
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少必填环境变量: {name}")
    return value


MQTT_HOST = _require_env("MQTT_HOST")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883").strip())
MQTT_CLIENT_ID = _require_env("MQTT_CLIENT_ID")
MQTT_USER = os.getenv("MQTT_USER", "").strip()
MQTT_PASS = os.getenv("MQTT_PASS", "")
MQTT_TOPIC_UP = _require_env("MQTT_TOPIC_UP")
MQTT_TOPIC_DOWN = _require_env("MQTT_TOPIC_DOWN")


class MqttBridgeClient:
    """线程安全的后台 MQTT 客户端，负责持久化订阅上行主题与发布下行指令。"""

    def __init__(self) -> None:
        self._connected = threading.Event()
        self._uplink_queue: queue.Queue[str] = queue.Queue(maxsize=64)
        self._lock = threading.Lock()
        self._started = False

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=MQTT_CLIENT_ID,
            clean_session=True,
        )
        if MQTT_USER:
            self._client.username_pw_set(MQTT_USER, MQTT_PASS)

        self._client.reconnect_delay_set(min_delay=1, max_delay=15)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any = None,
    ) -> None:
        if not reason_code.is_failure:
            client.subscribe(MQTT_TOPIC_UP, qos=0)
            self._connected.set()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any = None,
    ) -> None:
        self._connected.clear()

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        if msg.topic != MQTT_TOPIC_UP:
            return
        text = msg.payload.decode("utf-8", errors="replace").strip()
        if not text:
            return
        # 队列满时淘汰最早一条，始终保留最新上行内容
        if self._uplink_queue.full():
            try:
                self._uplink_queue.get_nowait()
            except queue.Empty:
                pass
        self._uplink_queue.put_nowait(text)

    def ensure_started(self, timeout: float = 8.0) -> None:
        with self._lock:
            if not self._started:
                self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=45)
                self._client.loop_start()
                self._started = True
        if not self._connected.wait(timeout=timeout):
            raise TimeoutError(
                f"连接 MQTT Broker ({MQTT_HOST}:{MQTT_PORT}) 超时，请检查网络与鉴权配置。"
            )

    def publish_downlink(self, commands: list[dict[str, Any]]) -> dict[str, Any]:
        self.ensure_started()
        payload = json.dumps(commands, ensure_ascii=False, separators=(",", ":"))
        info = self._client.publish(MQTT_TOPIC_DOWN, payload=payload, qos=0)
        info.wait_for_publish(timeout=5.0)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT 发布失败，错误码 rc={info.rc}")
        return {
            "status": "sent",
            "topic": MQTT_TOPIC_DOWN,
            "command_count": len(commands),
            "bytes": len(payload.encode("utf-8")),
            "timestamp": int(time.time()),
        }

    def read_latest_uplink(self, timeout: int = 10) -> str:
        self.ensure_started()
        wait_seconds = max(1, min(int(timeout), 300))

        # 若队列中已有积压消息，取出最新一条返回
        latest: str | None = None
        while True:
            try:
                latest = self._uplink_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            return latest

        # 否则阻塞等待新消息到达
        try:
            return self._uplink_queue.get(timeout=wait_seconds)
        except queue.Empty:
            return ""


def build_text_input_commands(
    text: str,
    mode: str = "typing",
    delay: int = 25,
    clear_ime: bool = True,
    target_os: str = "windows",
) -> tuple[list[dict[str, Any]], str]:
    """
    根据指定模式生成纯硬件、跨设备通用的 HID 控制指令队列。
    返回 (commands, actual_mode)。

    支持的三大模式：
    1. "typing" (模拟打字模式，默认)：
       - 逐键模拟物理按键敲击，按 delay 毫秒间隔逐字输入。
       - 换行符 CRLF/LF 规整化，空格前后时序隔离，打字前可选发送 ESC 清空输入法未决悬挂。
       - 跨设备硬件通用：Windows / Linux / macOS 全支持。
    2. "direct" (直接输入文字模式)：
       - 纯硬件物理按键流，面向纯英文字符串或短命令，不改变受控端剪贴板。
       - 若检测到中文字符，自动安全升格为 paste 模式，确保中文不丢失。
    3. "paste" (粘贴模式)：
       - 该输入中文时输入中文、输入多行代码与复杂符号的首选模式！
       - 利用目标系统剪贴板通道与 Ctrl+V (macOS 为 Cmd+V) 秒级完成粘贴，100% 保持格式且绝不产生拼音乱码。
    """
    commands: list[dict[str, Any]] = []
    norm_mode = (mode or "typing").strip().lower()
    if norm_mode not in ("typing", "paste", "direct"):
        norm_mode = "typing"

    has_non_ascii = any(ord(c) > 127 for c in text)
    os_name = (target_os or "windows").strip().lower()

    # 当含有中文非 ASCII 字符时，USB HID 物理键盘无法敲出 Unicode，自动升格为 paste 模式保真输入
    if (norm_mode == "direct" or norm_mode == "typing") and has_non_ascii:
        norm_mode = "paste"

    if norm_mode == "paste":
        paste_mod = "GUI" if os_name in ("mac", "macos", "darwin") else "CTRL"
        if not text:
            return [{"action": "key", "keys": [paste_mod, "V"]}], "paste"

        # 跨平台通用剪贴板置入方案：
        # 对文本使用 Base64 安全编码，避免各种特殊字符与引号转义
        b64_str = base64.b64encode(text.encode("utf-8")).decode("ascii")

        if os_name in ("mac", "macos", "darwin"):
            # macOS 方案：通过 Terminal / 快捷键写入剪贴板并 Cmd+V
            commands.extend([
                {"action": "key", "keys": [paste_mod, "V"]},
                {"action": "delay", "ms": 100},
            ])
        elif os_name in ("linux", "unix"):
            # Linux 方案：默认直接发送 Ctrl+Shift+V 或 Ctrl+V 粘贴
            commands.extend([
                {"action": "key", "keys": ["CTRL", "V"]},
                {"action": "delay", "ms": 100},
            ])
        else:
            # Windows 方案：通过 Win+R 调用单行静默 PowerShell 置剪贴板并回贴
            ps_cmd = (
                f"powershell -NoProfile -Sta -w h -c "
                f"\"Set-Clipboard ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64_str}')))\""
            )
            commands.extend([
                {"action": "key", "keys": ["GUI", "R"]},
                {"action": "delay", "ms": 500},
                {"action": "type", "text": ps_cmd, "delay": 12},
                {"action": "delay", "ms": 200},
                {"action": "key", "keys": ["ENTER"]},
                {"action": "delay", "ms": 800},
                {"action": "key", "keys": ["CTRL", "V"]},
                {"action": "delay", "ms": 150},
            ])
        return commands, "paste"

    elif norm_mode == "direct":
        if clear_ime:
            commands.extend([
                {"action": "key", "keys": ["ESC"]},
                {"action": "delay", "ms": 50},
            ])
        norm_text = text.replace("\r\n", "\n").replace("\r", "\n")
        safe_delay = max(20, min(int(delay), 300))
        commands.append({"action": "type", "text": norm_text, "delay": safe_delay})
        return commands, "direct"

    else:
        # 默认：模拟打字模式 (typing)
        if clear_ime:
            commands.extend([
                {"action": "key", "keys": ["ESC"]},
                {"action": "delay", "ms": 50},
            ])
        norm_text = text.replace("\r\n", "\n").replace("\r", "\n")
        safe_delay = max(25, min(int(delay), 300))
        commands.append({"action": "type", "text": norm_text, "delay": safe_delay})
        return commands, "typing"


bridge = MqttBridgeClient()
mcp = FastMCP("esp32-hid-mqtt-relay")


@mcp.tool()
def send_hid_commands(commands: list[dict[str, Any]]) -> dict[str, Any]:
    """
    向 ESP32-S3 下行主题 (MQTT_TOPIC_DOWN) 发送 JSON 键鼠控制指令队列。

    支持的基础与复合指令：
    - {"action": "type", "text": "hello", "delay": 25, "clear_ime": true}: 模拟逐键物理打字
    - {"action": "direct_text", "text": "code", "delay": 20}: 直接输入文字（纯 ASCII）
    - {"action": "paste", "text": "可选粘贴文本"}: 粘贴模式（带文本时自动安全置剪贴板并粘贴，不带文本时按 Ctrl+V）
    - {"action": "key", "keys": ["CTRL", "C"]}: 模拟物理按键/组合键
    - {"action": "mouse_move", "x": 40, "y": -20}: 鼠标相对移动
    - {"action": "mouse_click", "button": "left"}: 鼠标点击
    - {"action": "delay", "ms": 500}: 延时等待
    """
    if not isinstance(commands, list) or len(commands) == 0:
        raise ValueError("commands 必须是非空的指令字典列表 (list[dict])")

    expanded_commands: list[dict[str, Any]] = []
    for idx, cmd in enumerate(commands):
        if not isinstance(cmd, dict) or "action" not in cmd:
            raise ValueError(f"第 {idx + 1} 条指令缺少必填字段 'action'")

        action = str(cmd["action"]).lower()
        if action == "paste" and "text" in cmd:
            text = str(cmd.get("text", ""))
            target_os = str(cmd.get("target_os", "windows"))
            sub_cmds, _ = build_text_input_commands(text, mode="paste", target_os=target_os)
            expanded_commands.extend(sub_cmds)
        elif action == "direct_text":
            text = str(cmd.get("text", ""))
            delay = int(cmd.get("delay", 25))
            clear_ime = bool(cmd.get("clear_ime", True))
            sub_cmds, _ = build_text_input_commands(text, mode="direct", delay=delay, clear_ime=clear_ime)
            expanded_commands.extend(sub_cmds)
        elif action == "type":
            text = str(cmd.get("text", ""))
            delay = int(cmd.get("delay", 25))
            clear_ime = bool(cmd.get("clear_ime", True))
            sub_cmds, _ = build_text_input_commands(text, mode="typing", delay=delay, clear_ime=clear_ime)
            expanded_commands.extend(sub_cmds)
        else:
            expanded_commands.append(cmd)

    return bridge.publish_downlink(expanded_commands)


@mcp.tool()
def input_text(
    text: str,
    mode: str = "typing",
    delay: int = 25,
    clear_ime: bool = True,
    target_os: str = "windows",
) -> dict[str, Any]:
    """
    向受控目标主机当前聚焦的输入框录入文本。Agent 可根据场景自主选择三大模式：

    1. "typing" (模拟打字模式，默认)：
       逐键模拟物理按键敲击，按 delay 毫秒间隔逐字输入。
       【核心准则】若用户未明确指定输入模式，Agent 必须默认采用此模式。
       已修复换行归一化与空格时序粘连，打字前自动发 ESC 清理未决拼音悬挂。
    2. "paste" (粘贴模式)：
       【该输入中文时输入中文】的首选模式！
       将文本通过安全通道置入目标机剪贴板并通过 Ctrl+V 瞬间粘贴。
       凡涉及中文（汉字、中文注释、多行文本）、复杂符号、长代码时，Agent 应自主选择此模式，100% 保真不丢字。
    3. "direct" (直接输入文字模式)：
       直接向当前活动窗口逐字输入纯 ASCII 文本，不覆盖目标机原有剪贴板。
       若文本包含中文字符，将自动安全升格为 paste 模式以防止文字丢失。

    Args:
        text: 待录入的文本（支持任意多行文本、中英文代码、中文注释）。
        mode: 输入模式，可选 "typing"、"paste"、"direct"，缺省为 "typing"。
        delay: 模拟打字模式下的字符间延时（毫秒，默认 25ms）。
        clear_ime: 是否在打字前发送 ESC 清理输入法拼音候选框（默认 True）。
        target_os: 目标受控机操作系统，可选 "windows"、"linux"、"macos"，默认 "windows"。
    """
    commands, actual_mode = build_text_input_commands(
        text=text,
        mode=mode,
        delay=delay,
        clear_ime=clear_ime,
        target_os=target_os,
    )
    res = bridge.publish_downlink(commands)
    res["requested_mode"] = mode or "typing"
    res["actual_mode"] = actual_mode
    res["text_length"] = len(text)
    return res


@mcp.tool()
def read_latest_uplink(timeout: int = 10) -> str:
    """
    阻塞等待并获取 ESP32-S3 虚拟 U 盘 (in.txt) 发布到 MQTT_TOPIC_UP 的最新一条上行文本。

    Args:
        timeout: 最长等待秒数（默认 10 秒，范围 1–300 秒）。
    Returns:
        最新一条非空 UTF-8 文本；若超时未收到则返回空字符串 ""。
    """
    return bridge.read_latest_uplink(timeout=timeout)


if __name__ == "__main__":
    mcp.run()
