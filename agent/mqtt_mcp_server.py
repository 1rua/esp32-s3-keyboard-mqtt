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


bridge = MqttBridgeClient()
mcp = FastMCP("esp32-hid-mqtt-relay")


@mcp.tool()
def send_hid_commands(commands: list[dict[str, Any]]) -> dict[str, Any]:
    """
    向 ESP32-S3 下行主题 (MQTT_TOPIC_DOWN) 发送 JSON 键鼠控制指令队列。

    支持的指令示例：
    - {"action": "type", "text": "hello", "delay": 20}
    - {"action": "key", "keys": ["CTRL", "C"]}
    - {"action": "mouse_move", "x": 40, "y": -20}
    - {"action": "mouse_click", "button": "left"}
    - {"action": "delay", "ms": 500}
    """
    if not isinstance(commands, list) or len(commands) == 0:
        raise ValueError("commands 必须是非空的指令字典列表 (list[dict])")
    for idx, cmd in enumerate(commands):
        if not isinstance(cmd, dict) or "action" not in cmd:
            raise ValueError(f"第 {idx + 1} 条指令缺少必填字段 'action'")
    return bridge.publish_downlink(commands)


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
