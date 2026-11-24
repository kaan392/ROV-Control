/**
   @file ROV_Firmware.ino
   @brief Underwater ROV Firmware - Arduino Pro Mini (ATmega328P, 3.3V / 8MHz) + W5500

   PIN HARITASI
   ------------
   W5500 (SPI pinleri degistirilemez):
     SCS (CS)   -> D53
     MO  (MOSI) -> D51
     MI  (MISO) -> D50
     SCK        -> D52
     G          -> GND
     V          -> 3.3V
     RST, INT, NC -> baglanmaz

   ESC sinyal hatlari (Servo kutuphanesi, 50 Hz):
     M1 Arka Sol  -> D2
     M2 Arka Sag  -> D3
     M3 On Sol    -> D5
     M4 On Sag    -> D6
     M5 Sol Dikey -> D7
     M6 Sag Dikey -> D8

   Ayrilmis / kullanma:
     D0, D1 -> Serial debug için, ESC icin kullanilmaz
     D4, D9, A0-A5 -> bos olmalı
*/

#include <Arduino.h>
#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUdp.h>
#include <Servo.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

namespace Config {

namespace Hardware {
constexpr uint8_t PIN_ESC_M1 = 2; // Arka Sol Motor
constexpr uint8_t PIN_ESC_M2 = 3; // Arka Sag Motor
constexpr uint8_t PIN_ESC_M3 = 5; // On Sol Motor
constexpr uint8_t PIN_ESC_M4 = 6; // On Sag Motor
constexpr uint8_t PIN_ESC_M5 = 7; // Sol Dikey Motor
constexpr uint8_t PIN_ESC_M6 = 8; // Sag Dikey Motor
constexpr uint8_t THRUSTER_COUNT = 6;

constexpr uint8_t PIN_ETH_CS = 53; // W5500 SCS

// SPI (D10-D13) ve Serial (D0-D1) pinleri ESC icin kullanilamaz.
constexpr bool isReservedPin(uint8_t p) {
  return (p <= 1) || (p >= 10 && p <= 13);
}

static_assert(!isReservedPin(PIN_ESC_M1), "M1 pini SPI/Serial ile cakisiyor");
static_assert(!isReservedPin(PIN_ESC_M2), "M2 pini SPI/Serial ile cakisiyor");
static_assert(!isReservedPin(PIN_ESC_M3), "M3 pini SPI/Serial ile cakisiyor");
static_assert(!isReservedPin(PIN_ESC_M4), "M4 pini SPI/Serial ile cakisiyor");
static_assert(!isReservedPin(PIN_ESC_M5), "M5 pini SPI/Serial ile cakisiyor");
static_assert(!isReservedPin(PIN_ESC_M6), "M6 pini SPI/Serial ile cakisiyor");
}ww

// Normal şartlarda reverseleri oynama
namespace MotorDirection {
constexpr int8_t INVERT_M1 =  1;   // arka sol
constexpr int8_t INVERT_M2 =  1;   // arka sag
constexpr int8_t INVERT_M3 =  1;   // on sol
constexpr int8_t INVERT_M4 =  1;   // on sag
constexpr int8_t INVERT_M5 =  1;   // sol dikey
constexpr int8_t INVERT_M6 =  1;   // sag dikey
}

namespace Network {
constexpr uint8_t MAC_ADDRESS[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };
constexpr uint8_t IP_ADDRESS[]  = { 192, 168, 1, 50 };
constexpr uint8_t GATEWAY[]     = { 192, 168, 1, 1 };
constexpr uint8_t SUBNET[]      = { 255, 255, 255, 0 };
constexpr uint8_t DNS_SERVER[]  = { 192, 168, 1, 1 };

constexpr uint16_t LOCAL_PORT   = 5032;
constexpr uint8_t BUFFER_SIZE   = 64;

// Kablo (link) durumu kontrol araligi
constexpr unsigned long LINK_CHECK_INTERVAL_MS = 500;
}

namespace ESC {
constexpr uint16_t PWM_MIN     = 1000;
constexpr uint16_t PWM_NEUTRAL = 1500;
constexpr uint16_t PWM_MAX     = 2000;

constexpr uint32_t INIT_DELAY_MS = 2000;
}

namespace Motor {
constexpr int8_t PERCENT_MIN = -100;
constexpr int8_t PERCENT_MAX = 100;
constexpr int8_t DEADZONE    = 2;
}

namespace Safety {
// Python paket araliginin (ornegin 50-100 ms) en az 5 kati olmali.
constexpr unsigned long WATCHDOG_TIMEOUT_MS = 1000;
}

namespace Debug {
// Arac suda calisirken ENABLE_DEBUG = false yap.
constexpr bool ENABLE_DEBUG       = true;
constexpr unsigned long BAUDRATE  = 57600;  //seri monitör
constexpr bool PRINT_PACKETS      = true;   //gelen paket
constexpr bool PRINT_PWM          = true;   //giden paket
}

} // namespace Config

namespace Utilities {

template <typename T>
inline T clamp(T value, T minVal, T maxVal) {
  if (value < minVal) return minVal;
  if (value > maxVal) return maxVal;
  return value;
}

inline int8_t applyDeadzone(int8_t value, int8_t deadzone) {
  if (value >= -deadzone && value <= deadzone) {
    return 0;
  }
  return value;
}

inline uint16_t mapPercentToPWM(int8_t percentage, int8_t minPercent, int8_t maxPercent, uint16_t pwmMin, uint16_t pwmMax) {
  int8_t clampedPercent = clamp(percentage, minPercent, maxPercent);
  long numerator = (long)(clampedPercent - minPercent) * (long)(pwmMax - pwmMin);
  long denominator = (long)(maxPercent - minPercent);

  if (denominator == 0) return Config::ESC::PWM_NEUTRAL;

  long result = pwmMin + (numerator / denominator);
  return (uint16_t)clamp(result, (long)pwmMin, (long)pwmMax);
}
}

struct MotorOutputs {
  int8_t m1;
  int8_t m2;
  int8_t m3;
  int8_t m4;
  int8_t m5;
  int8_t m6;
};

struct ControlCommands {
  int8_t forward;
  int8_t strafe;
  int8_t yaw;
  int8_t vertical;
  bool emergencyStop;
  bool isValid;
  uint16_t sequence;     // Python'un paket numarasi (ACK icin)
  bool hasSequence;
  uint8_t reverseMask;
};

class ESCController {
  public:
    ESCController() {
      for (uint8_t i = 0; i < Config::Hardware::THRUSTER_COUNT; ++i) {
        m_currentPWM[i] = Config::ESC::PWM_NEUTRAL;
      }
    }

    void begin() {
      const uint8_t pins[Config::Hardware::THRUSTER_COUNT] = {
        Config::Hardware::PIN_ESC_M1, Config::Hardware::PIN_ESC_M2,
        Config::Hardware::PIN_ESC_M3, Config::Hardware::PIN_ESC_M4,
        Config::Hardware::PIN_ESC_M5, Config::Hardware::PIN_ESC_M6
      };

      for (uint8_t i = 0; i < Config::Hardware::THRUSTER_COUNT; ++i) {
        m_escs[i].attach(pins[i], Config::ESC::PWM_MIN, Config::ESC::PWM_MAX);
        m_escs[i].writeMicroseconds(Config::ESC::PWM_NEUTRAL);
      }

      delay(Config::ESC::INIT_DELAY_MS);
    }

    void setMotorPercent(uint8_t motorIndex, int8_t percentage) {
      if (motorIndex >= Config::Hardware::THRUSTER_COUNT) return;

      uint16_t pwmValue = Utilities::mapPercentToPWM(
                            percentage,
                            Config::Motor::PERCENT_MIN, Config::Motor::PERCENT_MAX,
                            Config::ESC::PWM_MIN, Config::ESC::PWM_MAX
                          );

      m_currentPWM[motorIndex] = pwmValue;
      m_escs[motorIndex].writeMicroseconds(pwmValue);
    }

    void stopAll() {
      for (uint8_t i = 0; i < Config::Hardware::THRUSTER_COUNT; ++i) {
        m_currentPWM[i] = Config::ESC::PWM_NEUTRAL;
        m_escs[i].writeMicroseconds(Config::ESC::PWM_NEUTRAL);
      }
    }

  private:
    Servo m_escs[Config::Hardware::THRUSTER_COUNT];
    uint16_t m_currentPWM[Config::Hardware::THRUSTER_COUNT];
};

class MotionController {
  public:
    MotionController() {}

    // Dort eksen de olu bolge icindeyse kumanda notr sayilir.
    bool isNeutral(const ControlCommands& c) const {
      return Utilities::applyDeadzone(c.forward,  Config::Motor::DEADZONE) == 0 &&
             Utilities::applyDeadzone(c.strafe,   Config::Motor::DEADZONE) == 0 &&
             Utilities::applyDeadzone(c.yaw,      Config::Motor::DEADZONE) == 0 &&
             Utilities::applyDeadzone(c.vertical, Config::Motor::DEADZONE) == 0;
    }

    MotorOutputs calculateOutputs(int8_t f, int8_t s, int8_t y, int8_t v, uint8_t reverseMask) {
      int forward = Utilities::applyDeadzone(f, Config::Motor::DEADZONE);
      int strafe  = Utilities::applyDeadzone(s, Config::Motor::DEADZONE);
      int yaw     = Utilities::applyDeadzone(y, Config::Motor::DEADZONE);
      int vert    = Utilities::applyDeadzone(v, Config::Motor::DEADZONE);

      int motors[4];

      // Capraz (X) duzen. Pozitif = ileri bilesenli itis.
      // Yanal sag: M1 ve M4 +, M2 ve M3 -.
      // yaw > 0: sag motorlar (M2, M4) +, sol motorlar (M1, M3) -
      //          (itis uzayinda; donus yonunu Python isaretiyle test ederek dogrula).
      motors[0] = forward + strafe - yaw; // M1 arka sol
      motors[1] = forward - strafe + yaw; // M2 arka sag
      motors[2] = forward - strafe - yaw; // M3 on sol
      motors[3] = forward + strafe + yaw; // M4 on sag

      int maxMagnitude = 0;

      for (int i = 0; i < 4; i++) {
        int magnitude = abs(motors[i]);
        if (magnitude > maxMagnitude) {
          maxMagnitude = magnitude;
        }
      }

      if (maxMagnitude > 100) {
        for (int i = 0; i < 4; i++) {
          motors[i] = (motors[i] * 100) / maxMagnitude;
        }
      }

      MotorOutputs outputs;

      outputs.m1 = (int8_t)Utilities::clamp(
                     motors[0] * Config::MotorDirection::INVERT_M1 * ((reverseMask & (1 << 0)) ? -1 : 1), -100, 100
                   );

      outputs.m2 = (int8_t)Utilities::clamp(
                     motors[1] * Config::MotorDirection::INVERT_M2 * ((reverseMask & (1 << 1)) ? -1 : 1), -100, 100
                   );

      outputs.m3 = (int8_t)Utilities::clamp(
                     motors[2] * Config::MotorDirection::INVERT_M3 * ((reverseMask & (1 << 2)) ? -1 : 1), -100, 100
                   );

      outputs.m4 = (int8_t)Utilities::clamp(
                     motors[3] * Config::MotorDirection::INVERT_M4 * ((reverseMask & (1 << 3)) ? -1 : 1), -100, 100
                   );

      outputs.m5 = (int8_t)Utilities::clamp(
                     vert * Config::MotorDirection::INVERT_M5 * ((reverseMask & (1 << 4)) ? -1 : 1), -100, 100
                   );

      outputs.m6 = (int8_t)Utilities::clamp(
                     vert * Config::MotorDirection::INVERT_M6 * ((reverseMask & (1 << 5)) ? -1 : 1), -100, 100
                   );

      return outputs;
    }
};

class PacketParser {
  public:
    PacketParser() {}

    ControlCommands parsePacket(const char* buffer, uint16_t length) {
      ControlCommands cmds = {0, 0, 0, 0, false, false, 0, false, 0};

      if (buffer == nullptr || length == 0) return cmds;

      if (strstr(buffer, "STOP") != nullptr || strstr(buffer, "EMERGENCY") != nullptr) {
        cmds.emergencyStop = true;
        cmds.isValid = true;
        return cmds;
      }

      int f = 0, s = 0, y = 0, v = 0, e = 0;
      if (sscanf(buffer, "F:%d,S:%d,Y:%d,V:%d,E:%d", &f, &s, &y, &v, &e) == 5) {
        cmds.forward  = (int8_t)Utilities::clamp(f, -100, 100);
        cmds.strafe   = (int8_t)Utilities::clamp(s, -100, 100);
        cmds.yaw      = (int8_t)Utilities::clamp(y, -100, 100);
        cmds.vertical = (int8_t)Utilities::clamp(v, -100, 100);
        cmds.emergencyStop = (e > 0);
        cmds.isValid  = true;

        const char* n = strstr(buffer, ",N:");
        if (n != nullptr) {
          cmds.sequence    = (uint16_t)atol(n + 3);
          cmds.hasSequence = true;
        }

        const char* r = strstr(buffer, ",R:");
        if (r != nullptr) {
          long mask = atol(r + 3);
          cmds.reverseMask = (uint8_t)Utilities::clamp(mask, 0L, 63L);
        }
      }

      return cmds;
    }
};

class EthernetReceiver {
  public:
    EthernetReceiver()
      : m_ip(Config::Network::IP_ADDRESS[0], Config::Network::IP_ADDRESS[1],
             Config::Network::IP_ADDRESS[2], Config::Network::IP_ADDRESS[3]) {}

    void begin() {
      Ethernet.init(Config::Hardware::PIN_ETH_CS);

      IPAddress dns(Config::Network::DNS_SERVER[0], Config::Network::DNS_SERVER[1], Config::Network::DNS_SERVER[2], Config::Network::DNS_SERVER[3]);
      IPAddress gateway(Config::Network::GATEWAY[0], Config::Network::GATEWAY[1], Config::Network::GATEWAY[2], Config::Network::GATEWAY[3]);
      IPAddress subnet(Config::Network::SUBNET[0], Config::Network::SUBNET[1], Config::Network::SUBNET[2], Config::Network::SUBNET[3]);

      Ethernet.begin((uint8_t*)Config::Network::MAC_ADDRESS, m_ip, dns, gateway, subnet);
      m_udp.begin(Config::Network::LOCAL_PORT);
    }

    bool isLinkUp() {
      return Ethernet.linkStatus() == LinkON;
    }

    // Kablo tekrar takilinca soketi temiz acmak icin
    void restartUdp() {
      m_udp.stop();
      m_udp.begin(Config::Network::LOCAL_PORT);
    }

    // Son gelen paketin sahibine "A:<seq>" cevabi yollar (Python tarafi gecikmeyi olcer).
    // Motorlar notr bekleme kilidindeyse "A:<seq>,H:1" olur.
    // readPacket()'ten sonra, bir sonraki parsePacket()'ten once cagrilmali.
    void sendAck(uint16_t seq, bool held) {
      char msg[16];
      snprintf(msg, sizeof(msg), "A:%u%s", (unsigned)seq, held ? ",H:1" : "");
      m_udp.beginPacket(m_udp.remoteIP(), m_udp.remotePort());
      m_udp.write((const uint8_t*)msg, strlen(msg));
      m_udp.endPacket();
    }

    uint16_t readPacket(char* outputBuffer, uint16_t maxLen) {
      int packetSize = m_udp.parsePacket();
      if (packetSize <= 0) return 0;

      int len = m_udp.read(outputBuffer, maxLen - 1);
      if (len > 0) {
        outputBuffer[len] = '\0';
        return (uint16_t)len;
      }

      return 0;
    }

  private:
    EthernetUDP m_udp;
    IPAddress m_ip;
};

ESCController     escController;
MotionController  motionController;
PacketParser      packetParser;
EthernetReceiver  ethernetReceiver;

char packetBuffer[Config::Network::BUFFER_SIZE];
unsigned long lastPacketTime = 0;

// true iken motorlar kilitli: acilista, kablo/haberlesme kesilince set edilir,
// kumanda bir kez notre donunce kalkar (baglanti donunca arac firlamasin).
bool waitingForNeutral = true;

void setup() {
  if (Config::Debug::ENABLE_DEBUG) {
    Serial.begin(Config::Debug::BAUDRATE);
    delay(500);
    Serial.println(F("--- SISTEM BASLADI ---"));
  }

  escController.begin();
  if (Config::Debug::ENABLE_DEBUG) {
    Serial.println(F("ESC'ler hazir."));
  }

  pinMode(10, OUTPUT);
  digitalWrite(10, HIGH);
  delay(200);
  ethernetReceiver.begin();

  // W5500 donanim kontrolu (kablo durumunu loop() 500 ms'de bir izliyor)
  if (Config::Debug::ENABLE_DEBUG &&
      Ethernet.hardwareStatus() == EthernetNoHardware) {
    Serial.println(F("HATA: W5500 bulunamadi! SPI kablolarini ve 3.3V gucu kontrol et."));
  }

  lastPacketTime = millis();
}

void loop() {
  // --- Ethernet kablo (link) takibi: 500 ms'de bir, sadece durum degisince mesaj ---
  static unsigned long lastLinkCheck = 0;
  static int8_t linkState = -1;  // -1: bilinmiyor, 0: kopuk, 1: bagli

  if (millis() - lastLinkCheck >= Config::Network::LINK_CHECK_INTERVAL_MS) {
    lastLinkCheck = millis();
    int8_t nowState = ethernetReceiver.isLinkUp() ? 1 : 0;

    if (nowState != linkState) {
      linkState = nowState;

      if (nowState == 1) {
        ethernetReceiver.restartUdp();
        lastPacketTime = millis();  // watchdog'u yeni baglantidan itibaren say
        if (Config::Debug::ENABLE_DEBUG) {
          Serial.print(F("Ag hazir. IP: "));
          Serial.println(Ethernet.localIP());
        }
      } else {
        escController.stopAll();   // kablo koptu -> motorlari hemen durdur
        waitingForNeutral = true;  // baglanti donunca kumanda notre donene kadar kilitli
        if (Config::Debug::ENABLE_DEBUG) {
          Serial.println(F("UYARI: Ethernet kablosu takili degil!"));
        }
      }
    }
  }

  uint16_t bytesRead = ethernetReceiver.readPacket(packetBuffer, Config::Network::BUFFER_SIZE);

  if (bytesRead > 0) {
    if (Config::Debug::ENABLE_DEBUG && Config::Debug::PRINT_PACKETS) {
      Serial.print(F("RX: "));
      Serial.println(packetBuffer);
    }

    ControlCommands cmds = packetParser.parsePacket(packetBuffer, bytesRead);

    if (cmds.isValid) {
      lastPacketTime = millis();

      if (waitingForNeutral && !cmds.emergencyStop && motionController.isNeutral(cmds)) {
        waitingForNeutral = false;
        if (Config::Debug::ENABLE_DEBUG) {
          Serial.println(F("Kumanda notr: motorlar aktif."));
        }
      }

      if (cmds.hasSequence) {
        ethernetReceiver.sendAck(cmds.sequence, waitingForNeutral);
      }

      if (cmds.emergencyStop || waitingForNeutral) {
        escController.stopAll();
      } else {
        MotorOutputs outputs = motionController.calculateOutputs(
                                 cmds.forward,
                                 cmds.strafe,
                                 cmds.yaw,
                                 cmds.vertical,
                                 cmds.reverseMask
                               );

        escController.setMotorPercent(0, outputs.m1);
        escController.setMotorPercent(1, outputs.m2);
        escController.setMotorPercent(2, outputs.m3);
        escController.setMotorPercent(3, outputs.m4);
        escController.setMotorPercent(4, outputs.m5);
        escController.setMotorPercent(5, outputs.m6);

        if (Config::Debug::ENABLE_DEBUG && Config::Debug::PRINT_PWM) {
          Serial.print(F("M%: "));
          Serial.print((int)outputs.m1); Serial.print(' ');
          Serial.print((int)outputs.m2); Serial.print(' ');
          Serial.print((int)outputs.m3); Serial.print(' ');
          Serial.print((int)outputs.m4); Serial.print(' ');
          Serial.print((int)outputs.m5); Serial.print(' ');
          Serial.println((int)outputs.m6);
        }
      }
    }
  }

  // Haberlesme kesilirse WATCHDOG_TIMEOUT_MS sonra tum motorlar notre alinir.
  if (millis() - lastPacketTime > Config::Safety::WATCHDOG_TIMEOUT_MS) {
    escController.stopAll();
    if (!waitingForNeutral) {
      waitingForNeutral = true;
      if (Config::Debug::ENABLE_DEBUG) {
        Serial.println(F("UYARI: Haberlesme kesildi, motorlar kumanda notre donene kadar kilitli."));
      }
    }
  }
}
