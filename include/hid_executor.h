#pragma once

#include <Arduino.h>

/**
 * 下行 HID 键鼠控制执行器
 * 支持单条 JSON 对象或 JSON 数组批量指令：
 * - {"action":"type", "text":"...", "delay":20}
 * - {"action":"key", "keys":["CTRL","C"]}
 * - {"action":"mouse_move", "x":10, "y":-10}
 * - {"action":"mouse_click", "button":"left", "double":false}
 * - {"action":"delay", "ms":500}
 */
class HidExecutor {
 public:
  // 注册 USBHIDKeyboard 与 USBHIDMouse（需在 USB.begin() 前调用）
  static void begin();

  // 解析并执行来自 MQTT topic_down 的 JSON 负载
  static void executeJson(const String& jsonPayload);

 private:
  static uint8_t mapKeyToken(const String& token);
  static void handleType(const String& text, uint16_t charDelayMs);
  static void handleMouseMove(int32_t dx, int32_t dy);
  static void handleMouseClick(const String& button, bool isDouble);
};
