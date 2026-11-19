#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESP32-S3 固件编译与烧录辅助脚本 (flash.py)
自动检测 PlatformIO 环境、识别可用串口并调用 pio 执行编译与烧录。
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_pio_executable() -> str:
    """寻找 platformio (pio) 可执行文件路径"""
    # 1. 优先检查 PATH
    pio_path = shutil.which("pio")
    if pio_path:
        return pio_path

    # 2. 检查常见默认安装路径
    candidates = [
        Path.home() / ".platformio" / "penv" / "bin" / "pio",
        Path.home() / ".local" / "bin" / "pio",
        Path("/usr/local/bin/pio"),
        Path("/usr/bin/pio"),
    ]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return str(c)

    return ""


def list_serial_ports() -> list[str]:
    """列出系统中可能为 ESP32 的串口设备"""
    ports = []
    # Linux 常见串口设备
    dev_dir = Path("/dev")
    if dev_dir.exists():
        for pattern in ["ttyACM*", "ttyUSB*"]:
            for p in dev_dir.glob(pattern):
                ports.append(str(p))

    # 如果系统有 pyserial，也可用 list_ports
    try:
        from serial.tools import list_ports
        for info in list_ports.comports():
            if info.device not in ports:
                ports.append(info.device)
    except ImportError:
        pass

    return sorted(ports)


def run_command(cmd: list[str], cwd: str) -> int:
    """运行子进程并实时流式输出日志"""
    print(f"[执行命令] {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
        for line in proc.stdout:
            print(line, end="", flush=True)
        proc.wait()
        return proc.returncode
    except Exception as e:
        print(f"[错误] 执行失败: {e}", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description="ESP32-S3 固件编译与烧录工具")
    parser.add_argument(
        "--env",
        default="esp32-s3-devkitc-1",
        choices=["esp32-s3-devkitc-1", "esp32-s3-n16r8", "esp32-s3-single-usb"],
        help="目标硬件环境（默认: esp32-s3-devkitc-1）",
    )
    parser.add_argument("--port", default=None, help="指定烧录串口（如 /dev/ttyACM0 或 COM3）")
    parser.add_argument("--check-only", action="store_true", help="仅检查环境和串口，不执行编译烧录")
    parser.add_argument("--build-only", action="store_true", help="仅编译固件，不执行烧录")
    parser.add_argument("--project-dir", default=None, help="项目根目录（含 platformio.ini）")

    args = parser.parse_args()

    # 确定项目根目录
    if args.project_dir:
        proj_dir = Path(args.project_dir).resolve()
    else:
        # 脚本所在目录往上找包含 platformio.ini 的目录
        current = Path(__file__).resolve().parent
        proj_dir = None
        while current != current.parent:
            if (current / "platformio.ini").exists():
                proj_dir = current
                break
            current = current.parent
        if not proj_dir:
            proj_dir = Path.cwd()

    if not (proj_dir / "platformio.ini").exists():
        print(f"[错误] 未在 {proj_dir} 找到 platformio.ini！请指定正确的 --project-dir", file=sys.stderr)
        sys.exit(1)

    print(f"=== ESP32-S3 固件构建与烧录检查 ===")
    print(f"项目目录: {proj_dir}")

    # 检查 pio 可执行文件
    pio_bin = find_pio_executable()
    if not pio_bin:
        print("[错误] 未找到 PlatformIO Core (pio) 可执行文件！", file=sys.stderr)
        print("请确认已安装 PlatformIO，例如运行: pip install platformio", file=sys.stderr)
        sys.exit(1)
    print(f"PlatformIO 路径: {pio_bin}")

    # 检查串口设备
    ports = list_serial_ports()
    print(f"检测到可用串口设备: {ports if ports else '暂未检测到串口设备'}")

    if args.check_only:
        print("[完成] 环境检查通过！")
        return

    # 仅编译模式
    if args.build_only:
        print(f"\n开始编译固件 (环境: {args.env})...")
        ret = run_command([pio_bin, "run", "-e", args.env], str(proj_dir))
        if ret == 0:
            print("\n[成功] 固件编译完成！")
        else:
            print("\n[失败] 固件编译失败，请查看上方错误输出。", file=sys.stderr)
        sys.exit(ret)

    # 确定烧录串口
    target_port = args.port
    if not target_port:
        if len(ports) == 1:
            target_port = ports[0]
            print(f"自动选用唯一串口: {target_port}")
        elif len(ports) > 1:
            print(f"[提示] 检测到多个串口: {', '.join(ports)}")
            print(f"默认交由 PlatformIO 自动探测，或使用 --port 指定。")
        else:
            print("[警告] 未检测到任何串口设备！请确认：")
            print("  1. 开发板的 UART (COM) 端口已通过 USB 线连入主机；")
            print("  2. USB 线具备数据传输功能，非仅供电线；")
            print("  3. 尝试按住板载 BOOT 键重新插拔以进入下载模式。")
            print("尝试交由 PlatformIO 自动扫描...")

    cmd = [pio_bin, "run", "-e", args.env, "-t", "upload"]
    if target_port:
        cmd.extend(["--upload-port", target_port])

    print(f"\n开始编译并烧录固件 (环境: {args.env})...")
    ret = run_command(cmd, str(proj_dir))
    if ret == 0:
        print("\n" + "=" * 60)
        print("[成功] 固件编译并烧录成功！")
        print("【下一步硬件接线重要提醒】")
        print("1. 固件已成功刷入 ESP32-S3 Flash 中。")
        print("2. 接下来请将开发板的【原生 USB-OTG 口】（而非 UART 口）连接至受控目标主机（电脑）。")
        print("3. 开发板将枚举为 HID 键鼠 + 卷标为 ESP32_RELAY 的 64KB 虚拟 U 盘。")
        print("=" * 60)
    else:
        print("\n" + "=" * 60, file=sys.stderr)
        print("[失败] 烧录失败！常见原因及排查方案：", file=sys.stderr)
        print("1. 权限不足（Linux）：执行 sudo usermod -a -G dialout $USER 并重新登录，或 sudo chmod 666 /dev/ttyUSB*", file=sys.stderr)
        print("2. 芯片未响应：按住板载 BOOT 键，按一下 RST (EN) 键，然后再尝试烧录。", file=sys.stderr)
        print("3. 端口占用：关闭正在监控串口日志的其他串口助手或终端。", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
    sys.exit(ret)


if __name__ == "__main__":
    main()
