#pragma once

#include <Arduino.h>
#include "config_store.h"

class CaptivePortal {
 public:
  /**
   * 进入阻塞式配网模式：
   * 1. 启动 SoftAP 热点 (ESP32-HID-Setup，固定 IP 192.168.4.1)
   * 2. 启动 DNSServer 将所有域名劫持到 192.168.4.1（强制门户弹窗）
   * 3. 提供内联 HTML/CSS 表单，保存至 NVS 后自动重启
   */
  static void runBlocking(const DeviceConfig& existingCfg);

 private:
  static String htmlEscape(const String& raw);
  static String renderFormPage(const DeviceConfig& cfg, const String& errorMsg);
};
