#include "ram_disk.h"
#include <USBMSC.h>
#include <cstring>
#include "tusb.h"

namespace {
USBMSC gMsc;
// 64KB 虚拟磁盘缓冲区（位于内部 RAM）
uint8_t gRamDisk[128 * 512];

volatile bool gWritePending     = false;
volatile uint32_t gLastWriteMs  = 0;
RamDiskMSC::UplinkHandler gUplinkHandler = nullptr;

inline void writeLe16(uint8_t* p, uint16_t v) {
  p[0] = static_cast<uint8_t>(v & 0xFF);
  p[1] = static_cast<uint8_t>((v >> 8) & 0xFF);
}

inline void writeLe32(uint8_t* p, uint32_t v) {
  p[0] = static_cast<uint8_t>(v & 0xFF);
  p[1] = static_cast<uint8_t>((v >> 8) & 0xFF);
  p[2] = static_cast<uint8_t>((v >> 16) & 0xFF);
  p[3] = static_cast<uint8_t>((v >> 24) & 0xFF);
}

inline uint16_t readLe16(const uint8_t* p) {
  return static_cast<uint16_t>(p[0]) | (static_cast<uint16_t>(p[1]) << 8);
}

inline uint32_t readLe32(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) |
         (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) |
         (static_cast<uint32_t>(p[3]) << 24);
}
}  // namespace

void RamDiskMSC::resetDisk() {
  memset(gRamDisk, 0, sizeof(gRamDisk));

  // ---------- 扇区 0：FAT12 引导扇区 (BPB) ----------
  uint8_t* bpb = &gRamDisk[0];
  bpb[0] = 0xEB;
  bpb[1] = 0x3C;
  bpb[2] = 0x90;
  memcpy(&bpb[3], "MSDOS5.0", 8);
  writeLe16(&bpb[11], kSectorSize);   // 每扇区字节数: 512
  bpb[13] = 1;                        // 每簇扇区数: 1
  writeLe16(&bpb[14], 1);             // 保留扇区数: 1 (Sector 0)
  bpb[16] = 2;                        // FAT 表份数: 2 (Sector 1 & 2)
  writeLe16(&bpb[17], 16);            // 根目录项数: 16 (16*32 = 512B = Sector 3)
  writeLe16(&bpb[19], kSectorCount);  // 总扇区数: 128
  bpb[21] = 0xF8;                     // 介质描述符: 固定/可移动磁盘
  writeLe16(&bpb[22], 1);             // 每张 FAT 占 1 扇区
  writeLe16(&bpb[24], 1);             // 每磁道扇区数
  writeLe16(&bpb[26], 1);             // 磁头数
  bpb[36] = 0x80;                     // 驱动器号
  bpb[38] = 0x29;                     // 扩展引导签名
  writeLe32(&bpb[39], 0x20260001);    // 卷序列号
  memcpy(&bpb[43], "ESP32_RELAY", 11);
  memcpy(&bpb[54], "FAT12   ", 8);
  bpb[510] = 0x55;
  bpb[511] = 0xAA;

  // ---------- 扇区 1 & 2：FAT1 / FAT2 保留簇 0 与 1 ----------
  uint8_t* fat1 = &gRamDisk[kSectorSize * 1];
  uint8_t* fat2 = &gRamDisk[kSectorSize * 2];
  fat1[0] = 0xF8;
  fat1[1] = 0xFF;
  fat1[2] = 0xFF;
  memcpy(fat2, fat1, kSectorSize);

  // ---------- 扇区 3：根目录 (Volume Label + 空文件 IN.TXT) ----------
  uint8_t* root = &gRamDisk[kSectorSize * 3];

  // 目录项 0：卷标
  memcpy(&root[0], "ESP32_RELAY", 11);
  root[11] = 0x08;

  // 目录项 1：预置空文件 IN.TXT（0 字节，起始簇号 0）
  uint8_t* entry = &root[32];
  memcpy(&entry[0], "IN      TXT", 11);
  entry[11] = 0x20;  // Archive 属性
  writeLe16(&entry[26], 0);
  writeLe32(&entry[28], 0);
}

uint16_t RamDiskMSC::getFat12Entry(uint16_t cluster) {
  const uint8_t* fat1 = &gRamDisk[kSectorSize * 1];
  uint32_t byteOffset = (cluster * 3U) / 2U;
  if (byteOffset + 1 >= kSectorSize) {
    return 0xFFF;
  }
  uint16_t val = readLe16(&fat1[byteOffset]);
  return (cluster & 1U) ? (val >> 4) : (val & 0x0FFF);
}

String RamDiskMSC::extractInTxt() {
  const uint8_t* root = &gRamDisk[kSectorSize * 3];
  uint16_t firstCluster = 0;
  uint32_t fileSize = 0;
  bool found = false;

  // 遍历全部 16 个根目录项（兼容主机编辑器原子替换产生的新目录槽位）
  for (int i = 0; i < 16; ++i) {
    const uint8_t* e = &root[i * 32];
    if (e[0] == 0x00) break;     // 目录末尾
    if (e[0] == 0xE5) continue;  // 已删除项

    uint8_t attr = e[11];
    // 跳过长文件名(0x0F)、卷标(0x08)、子目录(0x10)
    if (attr == 0x0F || (attr & 0x08) || (attr & 0x10)) continue;

    char name[12];
    for (int j = 0; j < 11; ++j) {
      name[j] = static_cast<char>(toupper(e[j]));
    }
    name[11] = '\0';

    if (strcmp(name, "IN      TXT") == 0) {
      firstCluster = readLe16(&e[26]);
      fileSize = readLe32(&e[28]);
      found = true;
      break;
    }
  }

  if (!found || fileSize == 0 || firstCluster < 2) {
    return String();
  }

  const uint32_t maxBytes = kMaxDataClusters * kSectorSize;
  if (fileSize > maxBytes) {
    fileSize = maxBytes;
  }

  String result;
  result.reserve(fileSize + 1);

  uint16_t current = firstCluster;
  uint32_t remaining = fileSize;
  uint32_t guard = 0;

  while (current >= 2 && current < 0xFF8 && remaining > 0 && guard < kMaxDataClusters) {
    uint32_t sectorIdx = kDataStartSector + (current - 2);
    if (sectorIdx >= kSectorCount) break;

    uint32_t toCopy = (remaining > kSectorSize) ? kSectorSize : remaining;
    const char* src = reinterpret_cast<const char*>(&gRamDisk[sectorIdx * kSectorSize]);
    for (uint32_t k = 0; k < toCopy; ++k) {
      result += src[k];
    }

    remaining -= toCopy;
    current = getFat12Entry(current);
    ++guard;
  }

  // 去除可能存在的 UTF-8 BOM (EF BB BF)
  if (result.length() >= 3 &&
      static_cast<uint8_t>(result[0]) == 0xEF &&
      static_cast<uint8_t>(result[1]) == 0xBB &&
      static_cast<uint8_t>(result[2]) == 0xBF) {
    result.remove(0, 3);
  }

  result.trim();
  return result;
}

int32_t RamDiskMSC::onRead(uint32_t lba, uint32_t offset, void* buffer, uint32_t bufsize) {
  uint32_t addr = lba * kSectorSize + offset;
  if (addr + bufsize > sizeof(gRamDisk)) {
    return -1;
  }
  memcpy(buffer, &gRamDisk[addr], bufsize);
  return static_cast<int32_t>(bufsize);
}

int32_t RamDiskMSC::onWrite(uint32_t lba, uint32_t offset, uint8_t* buffer, uint32_t bufsize) {
  uint32_t addr = lba * kSectorSize + offset;
  if (addr + bufsize > sizeof(gRamDisk)) {
    return -1;
  }
  memcpy(&gRamDisk[addr], buffer, bufsize);

  // 注意：此回调在 TinyUSB 中断/任务上下文执行，绝不在此阻塞或发网络包
  gLastWriteMs = millis();
  gWritePending = true;
  return static_cast<int32_t>(bufsize);
}

bool RamDiskMSC::onStartStop(uint8_t power_condition, bool start, bool load_eject) {
  (void)power_condition;
  (void)start;
  (void)load_eject;
  return true;
}

void RamDiskMSC::softReconnectUsb() {
  Serial.println(F("[MSC] 执行 USB 软断开重连以刷新主机文件系统缓存..."));
  tud_disconnect();
  delay(300);
  tud_connect();
}

void RamDiskMSC::begin(UplinkHandler handler) {
  gUplinkHandler = handler;
  resetDisk();

  gMsc.vendorID("ESP32S3");
  gMsc.productID("HID_RELAY_MSC");
  gMsc.productRevision("1.0");
  gMsc.onRead(onRead);
  gMsc.onWrite(onWrite);
  gMsc.onStartStop(onStartStop);
  gMsc.mediaPresent(true);
  gMsc.begin(kSectorCount, kSectorSize);

  Serial.println(F("[MSC] 64KB FAT12 虚拟 U 盘已注册 (预置 in.txt)"));
}

void RamDiskMSC::loop() {
  if (!gWritePending) {
    return;
  }

  // 等待 1000ms 防抖窗口结束，确保主机已完成所有扇区写入与 FAT 表落盘
  if (millis() - gLastWriteMs < kDebounceMs) {
    return;
  }

  gWritePending = false;
  String content = extractInTxt();
  if (content.length() == 0) {
    return;
  }

  Serial.printf("[MSC] 检测到 in.txt 有效写入 (%u 字节)，准备上行发布...\n",
                static_cast<unsigned>(content.length()));

  if (gUplinkHandler != nullptr && gUplinkHandler(content)) {
    Serial.println(F("[MSC] 上行发布成功，重置内存盘并触发 USB 软重连"));
    resetDisk();
    softReconnectUsb();
  } else {
    Serial.println(F("[MSC] 上行发布失败（可能网络未就绪），保留数据等待下次重试"));
  }
}
