#pragma once

#include <Arduino.h>

/**
 * 设备运行配置结构（全部存储于 ESP32 NVS Flash，严禁在源码中硬编码）
 */
struct DeviceConfig {
  String ssid;           // Wi-Fi 名称
  String wifi_pass;      // Wi-Fi 密码（开放网络可为空）
  String mqtt_host;      // MQTT Broker 地址（如 bemfa.com 或自建 EMQX IP/域名）
  uint16_t mqtt_port;    // MQTT 端口（标准默认 1883，巴法云为 9501）
  String mqtt_client_id; // MQTT Client ID（巴法云填私钥，标准 Broker 填唯一设备 ID）
  String mqtt_user;      // MQTT 用户名（可选，巴法云留空）
  String mqtt_pass;      // MQTT 密码（可选，巴法云留空）
  String topic_up;       // 上行主题（虚拟 U 盘 in.txt 内容发布到此主题）
  String topic_down;     // 下行主题（订阅此主题接收 JSON 键鼠控制指令）

  /**
   * 校验配置是否完整有效
   */
  bool isValid() const {
    return ssid.length() > 0 &&
           mqtt_host.length() > 0 &&
           mqtt_port > 0 &&
           mqtt_client_id.length() > 0 &&
           topic_up.length() > 0 &&
           topic_down.length() > 0 &&
           topic_up != topic_down;
  }
};

class ConfigStore {
 public:
  // 从 NVS 加载配置；若无有效配置则返回 false
  static bool load(DeviceConfig& cfg);

  // 将配置持久化写入 NVS
  static bool save(const DeviceConfig& cfg);

  // 清空 NVS 中已保存的配置
  static void clear();

 private:
  static constexpr const char* kNamespace = "hid_relay_cfg";
};
