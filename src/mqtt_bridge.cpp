#include "mqtt_bridge.h"
#include <PubSubClient.h>
#include <WiFi.h>
#include "hid_executor.h"

namespace {
DeviceConfig gCfg;
WiFiClient gWifiClient;
PubSubClient gMqtt(gWifiClient);

uint32_t gLastWifiAttemptMs = 0;
uint32_t gLastMqttAttemptMs = 0;

// 下行指令队列（在 MQTT 回调中入队，在主循环 loop() 中安全执行 HID 动作）
constexpr size_t kQueueCap = 8;
String gDownlinkQueue[kQueueCap];
size_t gQueueHead = 0;
size_t gQueueTail = 0;
size_t gQueueCount = 0;

bool enqueueDownlink(const String& msg) {
  if (gQueueCount >= kQueueCap) {
    return false;
  }
  gDownlinkQueue[gQueueTail] = msg;
  gQueueTail = (gQueueTail + 1) % kQueueCap;
  ++gQueueCount;
  return true;
}

bool dequeueDownlink(String& out) {
  if (gQueueCount == 0) {
    return false;
  }
  out = gDownlinkQueue[gQueueHead];
  gDownlinkQueue[gQueueHead] = "";
  gQueueHead = (gQueueHead + 1) % kQueueCap;
  --gQueueCount;
  return true;
}
}  // namespace

void MqttBridge::onMqttMessage(char* topic, uint8_t* payload, unsigned int length) {
  if (String(topic) != gCfg.topic_down || length == 0) {
    return;
  }

  String msg;
  msg.reserve(length + 1);
  for (unsigned int i = 0; i < length; ++i) {
    msg += static_cast<char>(payload[i]);
  }

  if (!enqueueDownlink(msg)) {
    Serial.println(F("[MQTT] 下行队列已满，丢弃本条指令"));
  } else {
    Serial.printf("[MQTT] 收到下行指令 (%u 字节)，已入队待执行\n", length);
  }
}

void MqttBridge::begin(const DeviceConfig& cfg) {
  gCfg = cfg;
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(gCfg.ssid.c_str(), gCfg.wifi_pass.c_str());

  gMqtt.setServer(gCfg.mqtt_host.c_str(), gCfg.mqtt_port);
  gMqtt.setBufferSize(8192);
  gMqtt.setKeepAlive(45);
  gMqtt.setCallback(onMqttMessage);

  Serial.printf("[WiFi] 正在连接 SSID: %s\n", gCfg.ssid.c_str());
}

void MqttBridge::ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }
  uint32_t now = millis();
  if (now - gLastWifiAttemptMs < 5000) {
    return;
  }
  gLastWifiAttemptMs = now;
  Serial.println(F("[WiFi] 连接断开，正在重连..."));
  WiFi.reconnect();
}

void MqttBridge::ensureMqtt() {
  if (WiFi.status() != WL_CONNECTED || gMqtt.connected()) {
    return;
  }

  uint32_t now = millis();
  if (now - gLastMqttAttemptMs < 3000) {
    return;
  }
  gLastMqttAttemptMs = now;

  Serial.printf("[MQTT] 连接 %s:%u (ClientID=%s)...",
                gCfg.mqtt_host.c_str(), gCfg.mqtt_port, gCfg.mqtt_client_id.c_str());

  bool connected = false;
  if (gCfg.mqtt_user.length() > 0) {
    // 标准 MQTT Broker 账密认证模式
    connected = gMqtt.connect(gCfg.mqtt_client_id.c_str(),
                              gCfg.mqtt_user.c_str(),
                              gCfg.mqtt_pass.c_str());
  } else {
    // 巴法云或匿名 Broker 无账密连接模式
    connected = gMqtt.connect(gCfg.mqtt_client_id.c_str());
  }

  if (connected) {
    Serial.println(F(" 成功"));
    if (gMqtt.subscribe(gCfg.topic_down.c_str())) {
      Serial.printf("[MQTT] 已订阅下行主题: %s\n", gCfg.topic_down.c_str());
    }
  } else {
    Serial.printf(" 失败 (rc=%d)，3 秒后重试\n", gMqtt.state());
  }
}

bool MqttBridge::publishUplink(const String& payload) {
  if (!gMqtt.connected()) {
    return false;
  }
  bool ok = gMqtt.publish(gCfg.topic_up.c_str(), payload.c_str(), false);
  if (ok) {
    Serial.printf("[MQTT] 已发布上行消息 -> %s (%u 字节)\n",
                  gCfg.topic_up.c_str(), static_cast<unsigned>(payload.length()));
  }
  return ok;
}

bool MqttBridge::isConnected() {
  return gMqtt.connected();
}

void MqttBridge::loop() {
  ensureWifi();
  ensureMqtt();

  if (gMqtt.connected()) {
    gMqtt.loop();
  }

  // 从队列取出一条下行指令并交给 HID 执行器
  String cmdPayload;
  if (dequeueDownlink(cmdPayload)) {
    HidExecutor::executeJson(cmdPayload);
  }
}
