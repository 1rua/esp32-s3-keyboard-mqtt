"""
ESP32-S3 虚拟 U 盘上行监听守护脚本 (mqtt_watcher.py)

读取与 mqtt_mcp_server.py 相同的环境变量，持续订阅 MQTT_TOPIC_UP；
收到非空上行文本时即时打印，并调用 on_uplink_received() 触发 Agent Webhook / API。
"""

from __future__ import annotations

from datetime import datetime
import json
import os
import signal
import sys
import urllib.request
from typing import Any

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

load_dotenv()


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
AGENT_WEBHOOK_URL = os.getenv("AGENT_WEBHOOK_URL", "").strip()


def on_uplink_received(text: str, topic: str) -> None:
    """
    收到虚拟 U 盘非空上行文本后的业务回调钩子。
    可在此对接 Agent HTTP Webhook、飞书/钉钉机器人或本地任务队列。
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{ts}] 收到上行文本 ({topic}) | {len(text)} 字符:")
    print("-" * 60)
    print(text)
    print("-" * 60, flush=True)

    # 预留 Agent Webhook 调用示例（配置 AGENT_WEBHOOK_URL 后自动启用）
    if AGENT_WEBHOOK_URL:
        payload = json.dumps(
            {"source": "esp32_msc_uplink", "topic": topic, "text": text, "timestamp": ts},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            AGENT_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[Webhook] 回调成功 -> HTTP {resp.status}", flush=True)
        except Exception as exc:
            print(f"[Webhook] 回调失败: {exc}", file=sys.stderr, flush=True)


def main() -> None:
    # 若与标准 Broker 同机运行，建议通过环境变量为 watcher 提供独立 Client ID
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID,
        clean_session=True,
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    client.reconnect_delay_set(min_delay=1, max_delay=15)

    def handle_connect(
        c: mqtt.Client, userdata: Any, flags: Any, rc: Any, props: Any = None
    ) -> None:
        if not rc.is_failure:
            c.subscribe(MQTT_TOPIC_UP, qos=0)
            print(
                f"[Watcher] 已连接 {MQTT_HOST}:{MQTT_PORT}，正在监听上行主题: {MQTT_TOPIC_UP}",
                flush=True,
            )
        else:
            print(f"[Watcher] 连接被拒绝: {rc}", file=sys.stderr, flush=True)

    def handle_message(c: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        text = msg.payload.decode("utf-8", errors="replace").strip()
        if text:
            on_uplink_received(text, msg.topic)

    client.on_connect = handle_connect
    client.on_message = handle_message

    def shutdown(signum: int, frame: Any) -> None:
        print("\n[Watcher] 正在断开连接并退出...", flush=True)
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=45)
    client.loop_forever()


if __name__ == "__main__":
    main()
