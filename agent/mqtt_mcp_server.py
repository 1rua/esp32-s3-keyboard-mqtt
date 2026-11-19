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
    delay: int = 20,
    clear_ime: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """
    根据指定模式生成稳健的 HID 控制指令队列。
    返回 (commands, actual_mode)。

    支持三种模式：
    - "typing": 模拟打字模式（默认模式）。逐字符模拟按键敲击，自动做换行规整与按键时序防粘连。
    - "paste": 粘贴模式。通过 Base64 安全将任意中英文/代码写入目标机剪贴板并触发 Ctrl+V 粘贴。
    - "direct": 直接输入文字模式。适用于纯 ASCII 字符串，不经过剪贴板。
                若检测到非 ASCII 字符（如中文），自动降级/升格为 paste 模式，防止字符丢失。
    """
    commands: list[dict[str, Any]] = []
    norm_mode = (mode or "typing").strip().lower()
    if norm_mode not in ("typing", "paste", "direct"):
        norm_mode = "typing"

    has_non_ascii = any(ord(c) > 127 for c in text)

    # 若 direct 模式检测到非 ASCII 字符，因 USB HID 物理键无法直敲 Unicode，自动切换至 paste 模式保证不丢字
    if norm_mode == "direct" and has_non_ascii:
        norm_mode = "paste"

    if norm_mode == "paste":
        if not text:
            return [{"action": "key", "keys": ["CTRL", "V"]}], "paste"
        # 采用 Base64 编码，加固 PowerShell -NoProfile -Sta 参数以提速并防止冷启动异常
        b64_str = base64.b64encode(text.encode("utf-8")).decode("ascii")
        ps_cmd = (
            f"powershell -NoProfile -Sta -w h -c "
            f"\"Set-Clipboard ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64_str}')))\""
        )
        commands.extend([
            {"action": "key", "keys": ["GUI", "R"]},
            {"action": "delay", "ms": 500},  # 等待 Win+R 运行窗口完全就绪
            {"action": "type", "text": ps_cmd, "delay": 12},
            {"action": "delay", "ms": 200},
            {"action": "key", "keys": ["ENTER"]},
            {"action": "delay", "ms": 800},  # 等待 PowerShell 执行写入剪贴板并恢复原窗口焦点
            {"action": "key", "keys": ["CTRL", "V"]},
            {"action": "delay", "ms": 150},
        ])
        return commands, "paste"

    elif norm_mode == "direct":
        if clear_ime:
            commands.extend([
                {"action": "key", "keys": ["ESC"]},
                {"action": "delay", "ms": 40},
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
        safe_delay = max(25, min(int(delay), 300))  # 默认 25~35ms 保证 USB 报告与输入法队列消化
        commands.append({"action": "type", "text": norm_text, "delay": safe_delay})
        return commands, "typing"


bridge = MqttBridgeClient()
mcp = FastMCP("esp32-hid-mqtt-relay")


@mcp.tool()
def send_hid_commands(commands: list[dict[str, Any]]) -> dict[str, Any]:
    """
    向 ESP32-S3 下行主题 (MQTT_TOPIC_DOWN) 发送 JSON 键鼠控制指令队列。

    支持的基础与复合指令：
    - {"action": "type", "text": "hello", "delay": 20, "clear_ime": true}: 模拟逐键打字
    - {"action": "direct_text", "text": "code", "delay": 20}: 直接输入文字（纯 ASCII）
    - {"action": "paste", "text": "可选粘贴文本"}: 粘贴模式（带文本时自动安全置剪贴板并粘贴，不带文本时按 Ctrl+V）
    - {"action": "key", "keys": ["CTRL", "C"]}: 模拟按键/组合键
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
            # 复合粘贴：展开为置剪贴板并 Ctrl+V
            text = str(cmd.get("text", ""))
            sub_cmds, _ = build_text_input_commands(text, mode="paste")
            expanded_commands.extend(sub_cmds)
        elif action == "direct_text":
            text = str(cmd.get("text", ""))
            delay = int(cmd.get("delay", 20))
            clear_ime = bool(cmd.get("clear_ime", True))
            sub_cmds, _ = build_text_input_commands(text, mode="direct", delay=delay, clear_ime=clear_ime)
            expanded_commands.extend(sub_cmds)
        elif action == "type":
            text = str(cmd.get("text", ""))
            delay = int(cmd.get("delay", 20))
            clear_ime = bool(cmd.get("clear_ime", True))  # 统一默认 True，保持与 input_text 一致
            sub_cmds, _ = build_text_input_commands(text, mode="typing", delay=delay, clear_ime=clear_ime)
            expanded_commands.extend(sub_cmds)
        else:
            expanded_commands.append(cmd)

    return bridge.publish_downlink(expanded_commands)


@mcp.tool()
def input_text(
    text: str,
    mode: str = "typing",
    delay: int = 20,
    clear_ime: bool = True,
) -> dict[str, Any]:
    """
    向受控目标主机当前聚焦的输入框录入文本。提供三种模式：

    1. "typing" (模拟打字模式，默认):
       逐键模拟物理按键敲击，按 delay 毫秒间隔逐字输入。
       【注意】若用户未明确指定输入模式，Agent 必须默认采用此模式。
       已修复换行归一化与空格时序粘连，打字前自动清除未决拼音候选框。
    2. "paste" (粘贴模式):
       将文本安全写入目标机剪贴板并通过 Ctrl+V 瞬间粘贴。
       最适合多行代码、长文本或中英文混排场景，速度最快且 100% 杜绝输入法干扰与字符错乱。
    3. "direct" (直接输入文字模式):
       直接向当前活动窗口逐字输入纯 ASCII 文本，不覆盖目标机原有剪贴板。
       若文本包含中文字符，将自动升格为 paste 模式以防止文字丢失。

    Args:
        text: 待录入的文本（支持任意多行文本、中英文代码、注释）。
        mode: 输入模式，可选 "typing"、"paste"、"direct"，缺省为 "typing"。
        delay: 模拟打字模式下的字符间延时（毫秒，默认 20ms）。
        clear_ime: 是否在打字前发送 ESC 清理输入法拼音候选框（默认 True）。
    """
    commands, actual_mode = build_text_input_commands(
        text=text,
        mode=mode,
        delay=delay,
        clear_ime=clear_ime,
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
