#pragma once

#include <Arduino.h>

/**
 * 基于 ESP32-S3 内部 RAM 的 64KB FAT12 虚拟 U 盘（无需外置 SD 卡）
 * - 扇区大小：512 字节
 * - 扇区数量：128 扇区（总容量 65,536 字节 = 64 KB）
 * - 根目录预置空文件 IN.TXT
 * - 主机写入后触发 1000ms 防抖 -> 解析内容 -> 回调上传 -> 清空并执行 USB 软重连
 */
class RamDiskMSC {
 public:
  // 上行回调函数签名：返回 true 表示 MQTT 发布成功，允许清空并重连 USB
  using UplinkHandler = bool (*)(const String& payload);

  // 初始化 64KB FAT12 内存镜像并注册 TinyUSB MSC 设备（需在 USB.begin() 前调用）
  static void begin(UplinkHandler handler);

  // 在主循环中周期调用，处理 1000ms 防抖超时与安全上传
  static void loop();

  // 将内存盘重置为初始空 FAT12 状态（保留 0 字节 in.txt）
  static void resetDisk();

  // 从 FAT12 镜像中解析 IN.TXT 文件内容并去除首尾空白
  static String extractInTxt();

 private:
  static constexpr uint32_t kSectorSize      = 512;
  static constexpr uint32_t kSectorCount     = 128;   // 128 * 512 = 65,536 bytes (64KB)
  static constexpr uint32_t kDataStartSector = 4;     // 0:BPB, 1:FAT1, 2:FAT2, 3:RootDir
  static constexpr uint32_t kMaxDataClusters = kSectorCount - kDataStartSector;
  static constexpr uint32_t kDebounceMs      = 1000;

  static int32_t onRead(uint32_t lba, uint32_t offset, void* buffer, uint32_t bufsize);
  static int32_t onWrite(uint32_t lba, uint32_t offset, uint8_t* buffer, uint32_t bufsize);
  static bool onStartStop(uint8_t power_condition, bool start, bool load_eject);
  static uint16_t getFat12Entry(uint16_t cluster);
  static void softReconnectUsb();
};
