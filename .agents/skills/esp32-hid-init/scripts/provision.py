#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESP32-S3 配网与初始化工具 (provision.py)
用于向 ESP32 WebUI (192.168.4.1) 自动化推送 Wi-Fi 与 MQTT 配置。
"""

import argparse
import sys
import urllib.parse
import urllib.request
import urllib.error


def validate_config(args) -> tuple[bool, str]:
    if not args.ssid:
        return False, "缺少 Wi-Fi 名称 (SSID)"
    if not args.mqtt_host:
        return False, "缺少 MQTT Broker 地址 (mqtt_host)"
    if not args.mqtt_client_id:
        return False, "缺少 MQTT Client ID / 私钥 (mqtt_client_id)"
    if not args.topic_up:
        return False, "缺少上行主题 (topic_up)"
    if not args.topic_down:
        return False, "缺少下行主题 (topic_down)"
    if args.topic_up == args.topic_down:
        return False, "topic_up 与 topic_down 不能相同，避免 MQTT 消息回环！"
    return True, ""


def check_portal_reachable(portal_url: str, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(portal_url, headers={"User-Agent": "ESP32-Provisioner"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def submit_provision(portal_ip: str, data: dict, timeout: float = 8.0) -> tuple[bool, str]:
    url = f"http://{portal_ip}/save"
    encoded_data = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return True, content
    except urllib.error.HTTPError as e:
        return False, f"HTTP 错误 {e.code}: {e.read().decode('utf-8', errors='replace')}"
    except Exception as e:
        return False, f"网络请求失败: {e}"


def main():
    parser = argparse.ArgumentParser(description="ESP32-S3 自动化配网工具")
    parser.add_argument("--portal-ip", default="192.168.4.1", help="配网门户 IP 地址（默认: 192.168.4.1）")
    parser.add_argument("--ssid", required=True, help="Wi-Fi 名称 (SSID)")
    parser.add_argument("--wifi-pass", default="", help="Wi-Fi 密码（开放网络可留空）")
    parser.add_argument("--mqtt-type", choices=["bemfa", "standard"], default="bemfa", help="MQTT 模式：bemfa（巴法云）或 standard（标准Broker）")
    parser.add_argument("--mqtt-host", default="", help="MQTT Broker 地址（巴法云默认 bemfa.com）")
    parser.add_argument("--mqtt-port", type=int, default=0, help="MQTT 端口（巴法云默认 9501，标准默认 1883）")
    parser.add_argument("--mqtt-client-id", default="", help="巴法云填私钥，标准 Broker 填客户端唯一 ID")
    parser.add_argument("--mqtt-user", default="", help="MQTT 用户名（可选）")
    parser.add_argument("--mqtt-pass", default="", help="MQTT 密码（可选）")
    parser.add_argument("--topic-up", default="hidUp001", help="上行主题（虚拟U盘 -> Agent）")
    parser.add_argument("--topic-down", default="hidDown001", help="下行主题（Agent -> 键鼠控制）")

    args = parser.parse_args()

    # 应用预设默认值
    if args.mqtt_type == "bemfa":
        if not args.mqtt_host:
            args.mqtt_host = "bemfa.com"
        if not args.mqtt_port:
            args.mqtt_port = 9501
    else:
        if not args.mqtt_port:
            args.mqtt_port = 1883

    valid, err_msg = validate_config(args)
    if not valid:
        print(f"[参数错误] {err_msg}", file=sys.stderr)
        sys.exit(1)

    payload = {
        "ssid": args.ssid,
        "wifi_pass": args.wifi_pass,
        "mqtt_host": args.mqtt_host,
        "mqtt_port": str(args.mqtt_port),
        "mqtt_client_id": args.mqtt_client_id,
        "mqtt_user": args.mqtt_user,
        "mqtt_pass": args.mqtt_pass,
        "topic_up": args.topic_up,
        "topic_down": args.topic_down,
    }

    print("=== ESP32-S3 设备配网信息 ===")
    print(f"Wi-Fi SSID       : {payload['ssid']}")
    print(f"MQTT 服务地址    : {payload['mqtt_host']}:{payload['mqtt_port']}")
    print(f"MQTT Client ID   : {payload['mqtt_client_id']}")
    print(f"MQTT 认证用户    : {payload['mqtt_user'] if payload['mqtt_user'] else '(无)'}")
    print(f"上行主题 topic_up: {payload['topic_up']}")
    print(f"下行主题 topic_dn: {payload['topic_down']}")
    print("-" * 50)

    # 尝试连接配网门户
    portal_base = f"http://{args.portal_ip}/"
    print(f"正在探测 ESP32 配网热点门户: {portal_base} ...")
    reachable = check_portal_reachable(portal_base, timeout=2.5)

    if reachable:
        print("[在线] 成功探测到 ESP32 配网服务！正在提交配置...")
        ok, res = submit_provision(args.portal_ip, payload)
        if ok:
            print("[成功] 配置已成功写入 ESP32 NVS 闪存！")
            print("设备正在自动重启并连接 Wi-Fi 与 MQTT Broker...")
            sys.exit(0)
        else:
            print(f"[失败] 提交配置失败: {res}", file=sys.stderr)
            sys.exit(1)
    else:
        print("[未直连] 当前环境无法直接访问 http://192.168.4.1/。")
        print("\n【请按以下极简步骤完成配网】:")
        print("1. 确保 ESP32-S3 已通电。若此前配过网，可长按板载【BOOT (GPIO0)】键 3 秒，设备将开启热点【ESP32-HID-Setup】。")
        print("2. 使用手机或电脑连接 Wi-Fi 热点：ESP32-HID-Setup（无需密码）。")
        print("3. 连接后浏览器会自动弹出配网页（或手动访问 http://192.168.4.1/）。")
        print("4. 在配网页中填入上述参数，点击【保存并重启】即可！")
        print("\n或者在连接 ESP32-HID-Setup 热点的电脑终端直接运行：")
        curl_cmd = (
            f"curl -X POST http://192.168.4.1/save "
            f"-d 'ssid={urllib.parse.quote(payload['ssid'])}' "
            f"-d 'wifi_pass={urllib.parse.quote(payload['wifi_pass'])}' "
            f"-d 'mqtt_host={payload['mqtt_host']}' "
            f"-d 'mqtt_port={payload['mqtt_port']}' "
            f"-d 'mqtt_client_id={payload['mqtt_client_id']}' "
            f"-d 'mqtt_user={payload['mqtt_user']}' "
            f"-d 'mqtt_pass={payload['mqtt_pass']}' "
            f"-d 'topic_up={payload['topic_up']}' "
            f"-d 'topic_down={payload['topic_down']}'"
        )
        print(f"  {curl_cmd}\n")


if __name__ == "__main__":
    main()
