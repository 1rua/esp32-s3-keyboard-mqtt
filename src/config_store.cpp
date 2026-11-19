#include "config_store.h"
#include <Preferences.h>

bool ConfigStore::load(DeviceConfig& cfg) {
  Preferences prefs;
  // 以只读模式打开命名空间；首次烧录可能尚不存在该命名空间
  if (!prefs.begin(kNamespace, true)) {
    cfg.mqtt_port = 1883;
    return false;
  }

  cfg.ssid           = prefs.getString("ssid", "");
  cfg.wifi_pass      = prefs.getString("wifi_pass", "");
  cfg.mqtt_host      = prefs.getString("mqtt_host", "");
  cfg.mqtt_port      = prefs.getUShort("mqtt_port", 1883);
  cfg.mqtt_client_id = prefs.getString("mqtt_cid", "");
  cfg.mqtt_user      = prefs.getString("mqtt_user", "");
  cfg.mqtt_pass      = prefs.getString("mqtt_pass", "");
  cfg.topic_up       = prefs.getString("topic_up", "");
  cfg.topic_down     = prefs.getString("topic_down", "");

  prefs.end();
  return cfg.isValid();
}

bool ConfigStore::save(const DeviceConfig& cfg) {
  if (!cfg.isValid()) {
    return false;
  }

  Preferences prefs;
  if (!prefs.begin(kNamespace, false)) {
    return false;
  }

  prefs.putString("ssid", cfg.ssid);
  prefs.putString("wifi_pass", cfg.wifi_pass);
  prefs.putString("mqtt_host", cfg.mqtt_host);
  prefs.putUShort("mqtt_port", cfg.mqtt_port);
  prefs.putString("mqtt_cid", cfg.mqtt_client_id);
  prefs.putString("mqtt_user", cfg.mqtt_user);
  prefs.putString("mqtt_pass", cfg.mqtt_pass);
  prefs.putString("topic_up", cfg.topic_up);
  prefs.putString("topic_down", cfg.topic_down);

  prefs.end();
  return true;
}

void ConfigStore::clear() {
  Preferences prefs;
  if (prefs.begin(kNamespace, false)) {
    prefs.clear();
    prefs.end();
  }
}
