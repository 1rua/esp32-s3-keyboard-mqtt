---
name: esp32-hid-mcp-setup
description: 自动化配置 Agent 端 Python 运行环境、依赖项、生成 agent/.env、测试 MQTT 连通性并注册 MCP Server（支持 DSH、Claude Desktop、Cursor）。当需要配置 Agent 接入端、生成 MCP 配置、测试 Broker 连接或配置环境变量时触发此技能。
---

# ESP32-S3 Agent 端环境与 MCP 服务配置指南

本技能负责准备本地 Python 运行环境、安装必要依赖、写入环境配置并输出各大 MCP 宿主的注册信息，验证与 MQTT Broker 的端到端连通性。

## 核心职责

1. **Python 运行环境与依赖管理**：
   - 使用项目内 `agent/.venv` 虚拟环境。
   - 依赖项：`fastmcp` (stdio MCP 通信), `paho-mqtt` (MQTT 客户端), `python-dotenv`。
2. **生成环境变量配置 (`agent/.env`)**：
   - 写入统一参数，避免手动编辑。
   - **防冲突策略**：标准 Broker 模式下，自动为 Agent 侧生成与 ESP32 不同的 Client ID（如 `<client_id>_mcp`），杜绝相互踢线死循环。
3. **连通性校验**：自动握手目标 Broker，验证鉴权与网络。
4. **生成 MCP 宿主注册片段**：
   - DSH 宿主（`~/.dsh/cordis.patch.yml`）
   - Claude Desktop（`claude_desktop_config.json`）
   - Cursor（`mcp.json`）

---

## 执行步骤

执行配套脚本 `scripts/setup_mcp.py`：

```bash
# 巴法云模式（提供私钥和主题）
python3 skills/esp32-hid-mcp-setup/scripts/setup_mcp.py \
  --mqtt-type bemfa \
  --mqtt-client-id "你的巴法云私钥UID" \
  --topic-up "hidUp001" \
  --topic-down "hidDown001"

# 标准 MQTT 模式
python3 skills/esp32-hid-mcp-setup/scripts/setup_mcp.py \
  --mqtt-type standard \
  --mqtt-host "192.168.1.100" \
  --mqtt-port 1883 \
  --mqtt-client-id "esp32_hid_relay_01" \
  --mqtt-user "admin" \
  --mqtt-pass "public" \
  --topic-up "esp32/up" \
  --topic-down "esp32/down"
```

## MCP 服务暴露的工具（Tools）

配置生效后，MCP 客户端将获得以下两个核心工具：
1. `send_hid_commands(commands: list[dict])`: 向目标主机下发键鼠控制 JSON 队列。
2. `read_latest_uplink(timeout: int = 10)`: 阻塞等待受控主机写入虚拟 U 盘并回传的最新非空文本。
