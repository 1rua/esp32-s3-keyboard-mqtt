#pragma once

#include <Arduino.h>
#include "config_store.h"

class MqttBridge {
 public:
  // 初始化 Wi-Fi 与 MQTT 客户端
  static void begin(const DeviceConfig& cfg);

  // 维护 Wi-Fi 与 MQTT 连接，并分发接收到的下行指令
  static void loop();

  // 向 topic_up 发布虚拟 U 盘上行文本
  static bool publishUplink(const String& payload);

  // 查询当前 MQTT 是否在线
  static bool isConnected();

 private:
  static void ensureWifi();
  static void ensureMqtt();
  static void onMqttMessage(char* topic, uint8_t* payload, unsigned int length);
};
