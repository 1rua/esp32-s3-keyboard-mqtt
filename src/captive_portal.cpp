#include "captive_portal.h"
#include <DNSServer.h>
#include <WebServer.h>
#include <WiFi.h>

namespace {
constexpr const char* kApSsid = "ESP32-HID-Setup";
constexpr uint8_t kDnsPort = 53;
const IPAddress kApIp(192, 168, 4, 1);
const IPAddress kApNetmask(255, 255, 255, 0);
}  // namespace

String CaptivePortal::htmlEscape(const String& raw) {
  String out;
  out.reserve(raw.length() + 16);
  for (size_t i = 0; i < raw.length(); ++i) {
    char c = raw[i];
    switch (c) {
      case '&':  out += F("&amp;");  break;
      case '<':  out += F("&lt;");   break;
      case '>':  out += F("&gt;");   break;
      case '"':  out += F("&quot;"); break;
      case '\'': out += F("&#39;");  break;
      default:   out += c;           break;
    }
  }
  return out;
}

String CaptivePortal::renderFormPage(const DeviceConfig& cfg, const String& errorMsg) {
  String html;
  html.reserve(4600);
  html += F(
      "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'>"
      "<meta name='viewport' content='width=device-width,initial-scale=1'>"
      "<title>ESP32-S3 HID 中转配网</title><style>"
      "*{box-sizing:border-box}body{margin:0;padding:18px;background:#f8fafc;color:#0f172a;"
      "font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;font-size:14px}"
      ".box{max-width:460px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;"
      "border-radius:10px;padding:22px}h1{margin:0 0 6px;font-size:18px}"
      ".sub{color:#64748b;font-size:12px;margin:0 0 16px}"
      ".presets{display:flex;gap:8px;margin-bottom:16px}"
      ".pbtn{flex:1;padding:8px;border:1px solid #cbd5e1;background:#f1f5f9;color:#0f172a;"
      "border-radius:6px;font-size:12px;cursor:pointer}"
      ".pbtn:hover{background:#e2e8f0}label{display:block;font-weight:600;margin:10px 0 4px;"
      "font-size:13px}input{width:100%;padding:9px 10px;border:1px solid #cbd5e1;"
      "border-radius:6px;font-size:14px;outline:none}input:focus{border-color:#1d4ed8}"
      ".row{display:flex;gap:10px}.row>div:first-child{flex:2}.row>div:last-child{flex:1}"
      ".hint{font-size:11px;color:#64748b;margin-top:3px}"
      ".err{background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;padding:10px;"
      "border-radius:6px;margin-bottom:12px;font-size:13px}"
      ".btn{width:100%;margin-top:18px;padding:11px;background:#1d4ed8;color:#fff;"
      "border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer}"
      ".btn:hover{background:#1e40af}</style></head><body><div class='box'>"
      "<h1>ESP32-S3 HID + U盘中转配网</h1>"
      "<p class='sub'>参数将写入 NVS 闪存持久化，支持巴法云（无账密）及 EMQX / Mosquitto。</p>");

  if (errorMsg.length() > 0) {
    html += F("<div class='err'>");
    html += htmlEscape(errorMsg);
    html += F("</div>");
  }

  html += F(
      "<div class='presets'>"
      "<button type='button' class='pbtn' onclick=\"fillPreset('bemfa')\">巴法云预设 (9501)</button>"
      "<button type='button' class='pbtn' onclick=\"fillPreset('emqx')\">标准 MQTT 预设 (1883)</button>"
      "</div><form method='POST' action='/save'>"
      "<label>Wi-Fi 名称 (SSID) *</label>"
      "<input name='ssid' required value='");
  html += htmlEscape(cfg.ssid);
  html += F(
      "' placeholder='输入 2.4GHz Wi-Fi 名称'>"
      "<label>Wi-Fi 密码</label>"
      "<input name='wifi_pass' type='password' value='");
  html += htmlEscape(cfg.wifi_pass);
  html += F(
      "' placeholder='无密码可留空'>"
      "<div class='row'><div><label>MQTT 服务器地址 *</label>"
      "<input id='host' name='mqtt_host' required value='");
  html += htmlEscape(cfg.mqtt_host);
  html += F(
      "' placeholder='bemfa.com 或 Broker IP'></div>"
      "<div><label>端口 *</label>"
      "<input id='port' name='mqtt_port' type='number' min='1' max='65535' required value='");
  html += String(cfg.mqtt_port > 0 ? cfg.mqtt_port : 1883);
  html += F(
      "'></div></div>"
      "<label>MQTT Client ID *</label>"
      "<input id='cid' name='mqtt_client_id' required value='");
  html += htmlEscape(cfg.mqtt_client_id);
  html += F(
      "' placeholder='巴法云填私钥 / 标准 Broker 填唯一 ID'>"
      "<div class='hint'>巴法云用户直接填写控制台私钥，下方用户名与密码留空即可。</div>"
      "<div class='row'><div><label>MQTT 用户名 (可选)</label>"
      "<input id='user' name='mqtt_user' value='");
  html += htmlEscape(cfg.mqtt_user);
  html += F(
      "' placeholder='可选'></div><div><label>MQTT 密码 (可选)</label>"
      "<input id='pass' name='mqtt_pass' type='password' value='");
  html += htmlEscape(cfg.mqtt_pass);
  html += F(
      "' placeholder='可选'></div></div>"
      "<label>上行主题 topic_up (虚拟U盘 -> Agent) *</label>"
      "<input id='up' name='topic_up' required value='");
  html += htmlEscape(cfg.topic_up);
  html += F(
      "' placeholder='例如 hid_relay_up004'>"
      "<label>下行主题 topic_down (Agent -> 键鼠控制) *</label>"
      "<input id='down' name='topic_down' required value='");
  html += htmlEscape(cfg.topic_down);
  html += F(
      "' placeholder='例如 hid_relay_down004'>"
      "<button type='submit' class='btn'>保存并重启</button></form>"
      "<script>function fillPreset(t){"
      "if(t==='bemfa'){host.value='bemfa.com';port.value='9501';user.value='';pass.value='';"
      "if(!up.value)up.value='hidUp004';if(!down.value)down.value='hidDown004';}"
      "else{if(!host.value||host.value==='bemfa.com')host.value='192.168.1.100';"
      "port.value='1883';if(!up.value)up.value='esp32/hid/up';if(!down.value)down.value='esp32/hid/down';}"
      "}</script></div></body></html>");
  return html;
}

void CaptivePortal::runBlocking(const DeviceConfig& existingCfg) {
  Serial.println(F("\n[Portal] 正在进入 AP 强制门户配网模式..."));

  WiFi.disconnect(true);
  delay(100);
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(kApIp, kApIp, kApNetmask);
  WiFi.softAP(kApSsid);

  Serial.printf("[Portal] 热点已开启: %s | 访问地址: http://%s/\n",
                kApSsid, WiFi.softAPIP().toString().c_str());

  DNSServer dnsServer;
  dnsServer.setErrorReplyCode(DNSReplyCode::NoError);
  dnsServer.start(kDnsPort, "*", kApIp);

  WebServer server(80);
  DeviceConfig workingCfg = existingCfg;
  if (workingCfg.mqtt_port == 0) {
    workingCfg.mqtt_port = 1883;
  }

  auto redirectToRoot = [&server]() {
    server.sendHeader(F("Location"), F("http://192.168.4.1/"), true);
    server.send(302, F("text/plain"), "");
  };

  server.on("/", HTTP_GET, [&server, &workingCfg]() {
    server.send(200, F("text/html; charset=utf-8"), renderFormPage(workingCfg, ""));
  });

  // 适配 Android / iOS / Windows 强制门户探测路径
  server.on("/generate_204", HTTP_GET, redirectToRoot);
  server.on("/hotspot-detect.html", HTTP_GET, redirectToRoot);
  server.on("/fwlink", HTTP_GET, redirectToRoot);
  server.on("/connecttest.txt", HTTP_GET, redirectToRoot);
  server.onNotFound(redirectToRoot);

  server.on("/save", HTTP_POST, [&server, &workingCfg]() {
    DeviceConfig nextCfg;
    nextCfg.ssid           = server.arg("ssid");           nextCfg.ssid.trim();
    nextCfg.wifi_pass      = server.arg("wifi_pass");
    nextCfg.mqtt_host      = server.arg("mqtt_host");      nextCfg.mqtt_host.trim();
    nextCfg.mqtt_port      = static_cast<uint16_t>(server.arg("mqtt_port").toInt());
    nextCfg.mqtt_client_id = server.arg("mqtt_client_id"); nextCfg.mqtt_client_id.trim();
    nextCfg.mqtt_user      = server.arg("mqtt_user");      nextCfg.mqtt_user.trim();
    nextCfg.mqtt_pass      = server.arg("mqtt_pass");
    nextCfg.topic_up       = server.arg("topic_up");       nextCfg.topic_up.trim();
    nextCfg.topic_down     = server.arg("topic_down");     nextCfg.topic_down.trim();

    workingCfg = nextCfg;

    if (!nextCfg.isValid()) {
      String reason = (nextCfg.topic_up == nextCfg.topic_down && nextCfg.topic_up.length() > 0)
                          ? F("上行主题与下行主题不能相同，请保持上下行解耦。")
                          : F("请完整填写所有必填项，并确保端口在 1–65535 之间。");
      server.send(400, F("text/html; charset=utf-8"), renderFormPage(workingCfg, reason));
      return;
    }

    if (!ConfigStore::save(nextCfg)) {
      server.send(500, F("text/html; charset=utf-8"),
                  renderFormPage(workingCfg, F("写入 NVS 失败，请重试。")));
      return;
    }

    server.send(200, F("text/html; charset=utf-8"),
                F("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'>"
                  "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                  "<title>保存成功</title></head>"
                  "<body style='font-family:sans-serif;text-align:center;padding:48px;color:#0f172a'>"
                  "<h2>配置已写入 NVS</h2>"
                  "<p style='color:#475569'>设备将在 1.5 秒后重启并连接目标 Wi-Fi 与 MQTT Broker。</p>"
                  "</body></html>"));

    Serial.println(F("[Portal] 配置保存成功，即将重启..."));
    delay(1500);
    ESP.restart();
  });

  server.begin();

  // 持续处理 DNS 与 HTTP 请求，直到用户提交保存并触发 ESP.restart()
  for (;;) {
    dnsServer.processNextRequest();
    server.handleClient();
    delay(5);
  }
}
