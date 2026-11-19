#include <Arduino.h>
#include <USB.h>
#include "captive_portal.h"
#include "config_store.h"
#include "hid_executor.h"
#include "mqtt_bridge.h"
#include "ram_disk.h"

namespace {
constexpr uint8_t kBootButtonPin      = 0;     // ESP32-S3 板载 BOOT 按钮 (低电平有效)
constexpr uint32_t kPortalHoldMs      = 3000;  // 长按 3 秒触发强制门户配网

DeviceConfig gDeviceConfig;
uint32_t gBootPressStartMs = 0;
bool gBootHolding          = false;

/**
 * 开机阶段检测是否长按 BOOT 键超过 3 秒
 */
bool checkBootButtonHoldOnStartup() {
  if (digitalRead(kBootButtonPin) != LOW) {
    return false;
  }
  Serial.println(F("[Boot] 检测到 BOOT 键按下，持续按住 3 秒将进入 WebUI 配网..."));
  uint32_t start = millis();
  while (digitalRead(kBootButtonPin) == LOW) {
    if (millis() - start >= kPortalHoldMs) {
      return true;
    }
    delay(20);
  }
  return false;
}

/**
 * 运行阶段持续轮询 BOOT 键，长按超过 3 秒即切换至配网模式
 */
void pollBootButtonRuntime() {
  if (digitalRead(kBootButtonPin) == LOW) {
    if (!gBootHolding) {
      gBootHolding = true;
      gBootPressStartMs = millis();
    } else if (millis() - gBootPressStartMs >= kPortalHoldMs) {
      Serial.println(F("[Boot] 运行期长按 BOOT 超过 3 秒，切换至 WebUI 配网模式"));
      CaptivePortal::runBlocking(gDeviceConfig);
    }
  } else {
    gBootHolding = false;
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(kBootButtonPin, INPUT_PULLUP);

  Serial.println(F("\n=== ESP32-S3 HID Relay + 64KB Virtual MSC 启动 ==="));

  bool hasValidConfig = ConfigStore::load(gDeviceConfig);
  bool forcePortal    = checkBootButtonHoldOnStartup();

  // 触发条件 1：NVS 无有效配置；触发条件 2：开机长按 BOOT > 3 秒
  if (!hasValidConfig || forcePortal) {
    if (!hasValidConfig) {
      Serial.println(F("[Boot] 未检测到有效 NVS 配置，自动进入配网模式"));
    }
    CaptivePortal::runBlocking(gDeviceConfig);
  }

  // 注册 USB 复合设备组件（必须先注册 HID 与 MSC，最后统一调用 USB.begin()）
  HidExecutor::begin();
  RamDiskMSC::begin(MqttBridge::publishUplink);
  USB.begin();
  Serial.println(F("[USB] TinyUSB 复合设备 (Keyboard + Mouse + 64KB MSC) 启动完成"));

  // 启动 Wi-Fi 与 MQTT 上下行桥接
  MqttBridge::begin(gDeviceConfig);
}

void loop() {
  pollBootButtonRuntime();
  MqttBridge::loop();
  RamDiskMSC::loop();
  delay(5);
}
