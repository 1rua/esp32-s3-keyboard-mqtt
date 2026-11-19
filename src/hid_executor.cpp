#include "hid_executor.h"
#include <ArduinoJson.h>
#include <USBHIDKeyboard.h>
#include <USBHIDMouse.h>

#ifndef KEY_PRINT_SCREEN
#define KEY_PRINT_SCREEN (0x46 + 0x88)  // HID_KEY_PRINT_SCREEN
#endif

namespace {
USBHIDKeyboard gKeyboard;
USBHIDMouse gMouse;
}  // namespace

void HidExecutor::begin() {
  gKeyboard.begin();
  gMouse.begin();
  Serial.println(F("[HID] USBHIDKeyboard 与 USBHIDMouse 已注册"));
}

uint8_t HidExecutor::mapKeyToken(const String& rawToken) {
  String t = rawToken;
  t.trim();
  t.toUpperCase();

  // 修饰键
  if (t == "CTRL" || t == "CONTROL" || t == "LCTRL") return KEY_LEFT_CTRL;
  if (t == "RCTRL")                                   return KEY_RIGHT_CTRL;
  if (t == "ALT" || t == "LALT")                      return KEY_LEFT_ALT;
  if (t == "RALT")                                    return KEY_RIGHT_ALT;
  if (t == "SHIFT" || t == "LSHIFT")                  return KEY_LEFT_SHIFT;
  if (t == "RSHIFT")                                  return KEY_RIGHT_SHIFT;
  if (t == "GUI" || t == "WIN" || t == "CMD" || t == "META" || t == "SUPER") {
    return KEY_LEFT_GUI;
  }

  // 控制与导航键
  if (t == "ENTER" || t == "RETURN")       return KEY_RETURN;
  if (t == "TAB")                          return KEY_TAB;
  if (t == "ESC" || t == "ESCAPE")         return KEY_ESC;
  if (t == "BACKSPACE" || t == "BS")       return KEY_BACKSPACE;
  if (t == "DELETE" || t == "DEL")         return KEY_DELETE;
  if (t == "SPACE")                        return ' ';
  if (t == "UP")                           return KEY_UP_ARROW;
  if (t == "DOWN")                         return KEY_DOWN_ARROW;
  if (t == "LEFT")                         return KEY_LEFT_ARROW;
  if (t == "RIGHT")                        return KEY_RIGHT_ARROW;
  if (t == "HOME")                         return KEY_HOME;
  if (t == "END")                          return KEY_END;
  if (t == "PAGEUP" || t == "PGUP")        return KEY_PAGE_UP;
  if (t == "PAGEDOWN" || t == "PGDN")      return KEY_PAGE_DOWN;
  if (t == "INSERT" || t == "INS")         return KEY_INSERT;
  if (t == "CAPSLOCK")                     return KEY_CAPS_LOCK;
  if (t == "PRINTSCREEN" || t == "PRTSC")  return KEY_PRINT_SCREEN;

  // 功能键 F1 - F12
  if (t == "F1")  return KEY_F1;
  if (t == "F2")  return KEY_F2;
  if (t == "F3")  return KEY_F3;
  if (t == "F4")  return KEY_F4;
  if (t == "F5")  return KEY_F5;
  if (t == "F6")  return KEY_F6;
  if (t == "F7")  return KEY_F7;
  if (t == "F8")  return KEY_F8;
  if (t == "F9")  return KEY_F9;
  if (t == "F10") return KEY_F10;
  if (t == "F11") return KEY_F11;
  if (t == "F12") return KEY_F12;

  // 单字符按键：组合键中的字母使用小写 ASCII，避免意外隐式附加 Shift
  if (rawToken.length() == 1) {
    char c = rawToken[0];
    if (c >= 'A' && c <= 'Z') {
      return static_cast<uint8_t>(c - 'A' + 'a');
    }
    return static_cast<uint8_t>(c);
  }

  return 0;
}

void HidExecutor::handleType(const String& text, uint16_t charDelayMs) {
  if (charDelayMs > 500) charDelayMs = 500;
  if (charDelayMs < 10) charDelayMs = 10;  // 保证基本按键间隔，防止丢键

  size_t len = text.length();
  for (size_t i = 0; i < len; ++i) {
    char c = text[i];

    // 处理换行符：兼容 Windows CRLF (\r\n)、Unix LF (\n)、以及单个 CR (\r)
    if (c == '\r') {
      if (i + 1 < len && text[i + 1] == '\n') {
        ++i;  // 跳过 CRLF 中的 \n，避免触发双次回车
      }
      gKeyboard.press(KEY_RETURN);
      delay(12);
      gKeyboard.release(KEY_RETURN);
      delay(max<uint16_t>(charDelayMs, 30));
      continue;
    }

    if (c == '\n') {
      gKeyboard.press(KEY_RETURN);
      delay(12);
      gKeyboard.release(KEY_RETURN);
      delay(max<uint16_t>(charDelayMs, 30));
      continue;
    }

    if (c == '\t') {
      gKeyboard.press(KEY_TAB);
      delay(10);
      gKeyboard.release(KEY_TAB);
      delay(charDelayMs);
      continue;
    }

    // 针对空格键加强时序隔离，消除输入法连带候选词错乱
    if (c == ' ') {
      delay(5);
      gKeyboard.press(' ');
      delay(10);
      gKeyboard.release(' ');
      delay(charDelayMs);
      continue;
    }

    // 标准可打印 ASCII 字符：严格保证按键按下保持时长与释放间隔
    if (c >= 0x20 && c <= 0x7E) {
      gKeyboard.press(static_cast<uint8_t>(c));
      delay(8);  // 保持 8ms 确保主机 USB HID 端点可靠采信
      gKeyboard.release(static_cast<uint8_t>(c));
      delay(charDelayMs);
    } else {
      // 捕获并提示非 ASCII 字符（如中文 UTF-8 多字节序列）
      Serial.printf("[HID] 提示: 物理键盘跳过非 ASCII 字符 (0x%02X)，建议使用粘贴模式 (paste)\n", static_cast<uint8_t>(c));
    }
  }
}

void HidExecutor::handleMouseMove(int32_t dx, int32_t dy) {
  // USB HID 鼠标报告单次位移范围为 int8 [-127, 127]，超出范围时自动分片发送
  while (dx != 0 || dy != 0) {
    int8_t stepX = static_cast<int8_t>(constrain(dx, -127L, 127L));
    int8_t stepY = static_cast<int8_t>(constrain(dy, -127L, 127L));
    gMouse.move(stepX, stepY, 0);
    dx -= stepX;
    dy -= stepY;
    delay(8);
  }
}

void HidExecutor::handleMouseClick(const String& button, bool isDouble) {
  String b = button;
  b.toLowerCase();

  uint8_t mask = MOUSE_LEFT;
  if (b == "right") {
    mask = MOUSE_RIGHT;
  } else if (b == "middle") {
    mask = MOUSE_MIDDLE;
  }

  gMouse.click(mask);
  if (isDouble) {
    delay(80);
    gMouse.click(mask);
  }
}

void HidExecutor::executeJson(const String& jsonPayload) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, jsonPayload);
  if (err) {
    Serial.printf("[HID] JSON 解析失败: %s\n", err.c_str());
    return;
  }

  auto runSingle = [](JsonObjectConst cmd) {
    const char* actionC = cmd["action"] | "";
    String action(actionC);
    action.toLowerCase();

    if (action == "type" || action == "direct_text") {
      String text = cmd["text"] | "";
      uint16_t charDelay = cmd["delay"] | 20;
      handleType(text, charDelay);
    } else if (action == "paste") {
      // 粘贴快捷键：默认发送 Ctrl + V (可通过 modifier 定制)
      String modifier = cmd["modifier"] | "CTRL";
      modifier.toUpperCase();
      uint8_t modKey = (modifier == "GUI" || modifier == "CMD") ? KEY_LEFT_GUI : KEY_LEFT_CTRL;
      gKeyboard.press(modKey);
      delay(10);
      gKeyboard.press('v');
      delay(15);
      gKeyboard.releaseAll();
      delay(50);
    } else if (action == "key") {
      JsonArrayConst keys = cmd["keys"].as<JsonArrayConst>();
      if (!keys.isNull() && keys.size() > 0) {
        for (JsonVariantConst v : keys) {
          uint8_t code = mapKeyToken(v.as<String>());
          if (code != 0) {
            gKeyboard.press(code);
            delay(10);
          }
        }
        delay(35);
        gKeyboard.releaseAll();
      }
    } else if (action == "mouse_move") {
      int32_t x = cmd["x"] | 0;
      int32_t y = cmd["y"] | 0;
      handleMouseMove(x, y);
    } else if (action == "mouse_click") {
      String btn = cmd["button"] | "left";
      bool isDouble = cmd["double"] | false;
      handleMouseClick(btn, isDouble);
    } else if (action == "delay") {
      uint32_t ms = cmd["ms"] | 0;
      if (ms > 30000) ms = 30000;
      // 分片延时，避免长阻塞触发看门狗
      uint32_t start = millis();
      while (millis() - start < ms) {
        delay(min<uint32_t>(25, ms - (millis() - start)));
      }
    } else {
      Serial.printf("[HID] 忽略未知指令 action: %s\n", action.c_str());
    }
  };

  if (doc.is<JsonArray>()) {
    for (JsonVariantConst item : doc.as<JsonArrayConst>()) {
      if (item.is<JsonObjectConst>()) {
        runSingle(item.as<JsonObjectConst>());
      }
    }
  } else if (doc.is<JsonObject>()) {
    runSingle(doc.as<JsonObjectConst>());
  } else {
    Serial.println(F("[HID] 不支持的 JSON 根节点类型（仅支持对象或数组）"));
  }
}
