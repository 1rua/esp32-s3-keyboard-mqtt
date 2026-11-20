#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 端 Python 运行环境与 MCP 服务配置工具 (setup_mcp.py)
配置 agent/.env、校验 Python 依赖、测试 MQTT 连通性，并生成 MCP 注册配置。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def find_python_executable(agent_dir: Path) -> str:
    """优先使用 agent/.venv 中的 Python，若不存在则回退至系统 python3"""
    candidates = [
        agent_dir / ".venv" / "bin" / "python",
        agent_dir / ".venv" / "bin" / "python3",
        agent_dir / ".venv" / "Scripts" / "python.exe",
    ]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return str(c)
    return sys.executable


def ensure_virtualenv(agent_dir: Path) -> str:
    """确保虚拟环境存在并具备基础依赖"""
    venv_dir = agent_dir / ".venv"
    python_bin = find_python_executable(agent_dir)

    if not venv_dir.exists():
        print(f"正在创建 Python 虚拟环境: {venv_dir} ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
        python_bin = find_python_executable(agent_dir)

    req_file = agent_dir / "requirements.txt"
    if req_file.exists():
        print("检查并安装 Python 依赖 (fastmcp, paho-mqtt, python-dotenv)...")
        subprocess.check_call([
            python_bin, "-m", "pip", "install", "-q", "-r", str(req_file)
        ])

    return python_bin


def test_mqtt_connection(python_bin: str, host: str, port: int, client_id: str, user: str, password: str, timeout: float = 6.0) -> tuple[bool, str]:
    """使用虚拟环境中的 Python 测试当前 MQTT 配置能否成功握手 Broker"""
    test_code = f"""
import sys, time
import paho.mqtt.client as mqtt

connected = False
err = ""

def on_connect(c, userdata, flags, rc, props=None):
    global connected, err
    if not rc.is_failure:
        connected = True
    else:
        err = f"Broker拒绝: {{rc}}"

c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="{client_id}", clean_session=True)
if "{user}":
    c.username_pw_set("{user}", "{password}")
c.on_connect = on_connect
try:
    c.connect("{host}", {port}, keepalive=15)
    c.loop_start()
    start = time.time()
    while time.time() - start < {timeout}:
        if connected or err:
            break
        time.sleep(0.2)
    c.loop_stop()
    c.disconnect()
    if connected:
        print("OK")
    else:
        print("FAIL:" + (err or "连接超时"))
except Exception as e:
    print(f"EXC:{{e}}")
"""
    try:
        proc = subprocess.run(
            [python_bin, "-c", test_code],
            capture_output=True,
            text=True,
            timeout=timeout + 3.0,
        )
        out = proc.stdout.strip()
        if "OK" in out:
            return True, "连接成功！Broker 握手响应正常。"
        elif out.startswith("FAIL:"):
            return False, out[5:]
        elif out.startswith("EXC:"):
            return False, out[4:]
        return False, out or proc.stderr.strip() or "未知测试错误"
    except Exception as e:
        return False, f"测试调用失败: {e}"


def main():
    parser = argparse.ArgumentParser(description="ESP32 HID MCP 服务配置工具")
    parser.add_argument("--mqtt-type", choices=["bemfa", "standard"], default="bemfa", help="MQTT 模式：bemfa 或 standard")
    parser.add_argument("--mqtt-host", default="", help="MQTT Broker 地址")
    parser.add_argument("--mqtt-port", type=int, default=0, help="MQTT 端口")
    parser.add_argument("--mqtt-client-id", required=True, help="MQTT Client ID（巴法云填私钥，标准填唯一ID）")
    parser.add_argument("--mqtt-user", default="", help="MQTT 用户名（可选）")
    parser.add_argument("--mqtt-pass", default="", help="MQTT 密码（可选）")
    parser.add_argument("--topic-up", default="hidUp001", help="上行主题")
    parser.add_argument("--topic-down", default="hidDown001", help="下行主题")
    parser.add_argument("--agent-dir", default=None, help="agent 目录路径")

    args = parser.parse_args()

    # 定位 agent 目录
    if args.agent_dir:
        agent_dir = Path(args.agent_dir).resolve()
    else:
        current = Path(__file__).resolve().parent
        agent_dir = None
        while current != current.parent:
            if (current / "agent" / "mqtt_mcp_server.py").exists():
                agent_dir = current / "agent"
                break
            current = current.parent
        if not agent_dir:
            agent_dir = Path.cwd() / "agent"

    if not (agent_dir / "mqtt_mcp_server.py").exists():
        print(f"[错误] 未在 {agent_dir} 找到 mqtt_mcp_server.py！", file=sys.stderr)
        sys.exit(1)

    # 填充默认参数
    host = args.mqtt_host
    port = args.mqtt_port
    if args.mqtt_type == "bemfa":
        if not host:
            host = "bemfa.com"
        if not port:
            port = 9501
        mcp_client_id = args.mqtt_client_id
    else:
        if not port:
            port = 1883
        # 标准 MQTT 下，Agent 客户端 ID 绝不能与 ESP32 设备相同，避免互相踢掉线
        mcp_client_id = args.mqtt_client_id
        if not mcp_client_id.endswith("_agent") and not mcp_client_id.endswith("_mcp"):
            mcp_client_id = f"{args.mqtt_client_id}_mcp"

    print("=== ESP32-S3 MCP 服务配置 ===")
    print(f"Agent 目录       : {agent_dir}")
    print(f"MQTT Broker      : {host}:{port}")
    print(f"Agent Client ID  : {mcp_client_id}")
    print(f"订阅上行 topic_up: {args.topic_up}")
    print(f"发布下行 topic_dn: {args.topic_down}")
    print("-" * 50)

    # 1. 确保 Python 虚拟环境与依赖
    python_bin = ensure_virtualenv(agent_dir)
    print(f"Python 解释器路径: {python_bin}")

    # 2. 生成 agent/.env 文件
    env_content = f"""# 由 esp32-hid-mcp-setup 自动生成
MQTT_HOST={host}
MQTT_PORT={port}
MQTT_CLIENT_ID={mcp_client_id}
MQTT_USER={args.mqtt_user}
MQTT_PASS={args.mqtt_pass}
MQTT_TOPIC_UP={args.topic_up}
MQTT_TOPIC_DOWN={args.topic_down}
"""
    env_file = agent_dir / ".env"
    env_file.write_text(env_content, encoding="utf-8")
    print(f"[成功] 配置文件已写入: {env_file}")

    # 3. 测试与 Broker 的连通性
    print("正在测试与 MQTT Broker 的网络连通性...")
    ok, msg = test_mqtt_connection(
        python_bin=python_bin,
        host=host,
        port=port,
        client_id=mcp_client_id,
        user=args.mqtt_user,
        password=args.mqtt_pass,
        timeout=5.0,
    )
    if ok:
        print(f"[验证通过] {msg}")
    else:
        print(f"[提示/警告] 连通性测试未通过: {msg}")
        print("请检查网络连接、防火墙或 Broker 是否已正常启动。")

    # 4. 生成 MCP 宿主配置样例
    server_py = (agent_dir / "mqtt_mcp_server.py").resolve()

    claude_desktop_cfg = {
        "mcpServers": {
            "esp32-hid-relay": {
                "command": str(python_bin),
                "args": [str(server_py)],
                "env": {
                    "MQTT_HOST": host,
                    "MQTT_PORT": str(port),
                    "MQTT_CLIENT_ID": mcp_client_id,
                    "MQTT_USER": args.mqtt_user,
                    "MQTT_PASS": args.mqtt_pass,
                    "MQTT_TOPIC_UP": args.topic_up,
                    "MQTT_TOPIC_DOWN": args.topic_down,
                },
            }
        }
    }

    print("\n" + "=" * 60)
    print("【Claude Desktop / Cursor 配置片段 (JSON)】:")
    print(json.dumps(claude_desktop_cfg, indent=2, ensure_ascii=False))
    print("=" * 60)

    # DSH cordis.patch.yml 格式
    dsh_entry = f"""
# DSH (~/.dsh/cordis.patch.yml) 配置片段：
- insert:
    - id: 'mcp-esp32-hid-relay'
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: 'esp32-hid-relay'
        transport: 'stdio'
        command: '{python_bin}'
        args:
          - '{server_py}'
        env:
          MQTT_HOST: '{host}'
          MQTT_PORT: '{port}'
          MQTT_CLIENT_ID: '{mcp_client_id}'
          MQTT_USER: '{args.mqtt_user}'
          MQTT_PASS: '{args.mqtt_pass}'
          MQTT_TOPIC_UP: '{args.topic_up}'
          MQTT_TOPIC_DOWN: '{args.topic_down}'
"""
    print(dsh_entry)
    print("[完成] MCP 服务环境配置就绪！")


if __name__ == "__main__":
    main()
