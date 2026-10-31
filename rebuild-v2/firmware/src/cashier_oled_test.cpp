#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <Keypad.h>
#include <MFRC522.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// Standalone Cashier hardware diagnostic: ESP32 + SSD1306 OLED + RC522 + 4x4 keypad. No PN532, LCD, Wi-Fi, server, member, or payment logic.
namespace {
constexpr uint8_t OLED_SDA = 21;
constexpr uint8_t OLED_SCL = 22;
constexpr uint8_t OLED_ADDRESS = 0x3C;
constexpr int8_t OLED_RESET = -1;
constexpr uint8_t RFID_SS = 27;
constexpr uint8_t RFID_RST = 4;
constexpr uint8_t RFID_SCK = 18;
constexpr uint8_t RFID_MISO = 19;
constexpr uint8_t RFID_MOSI = 23;

constexpr byte ROWS = 4;
constexpr byte COLS = 4;
char keyMap[ROWS][COLS] = {
  {'1','2','3','A'},
  {'4','5','6','B'},
  {'7','8','9','C'},
  {'*','0','#','D'}
};
byte rowPins[ROWS] = {32, 33, 25, 26};
byte colPins[COLS] = {13, 14, 16, 17};
Keypad keypad = Keypad(makeKeymap(keyMap), rowPins, colPins, ROWS, COLS);
Adafruit_SSD1306 display(128, 64, &Wire, OLED_RESET);
MFRC522 rfid(RFID_SS, RFID_RST);

String typed = "";
String lastUid = "";
bool oledReady = false;
bool rfidReady = false;
unsigned long lastScreenUpdate = 0;

void drawScreen(const String& line1, const String& line2 = "",
                const String& line3 = "", const String& line4 = "") {
  if (!oledReady) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println(line1);
  display.println(line2);
  display.println(line3);
  display.println(line4);
  display.display();
}

void showInput() {
  String masked;
  for (size_t i = 0; i < typed.length(); ++i) masked += '*';
  drawScreen("M-GROUP CASHIER TEST", "Keypad 4x4: OK", "Input: " + masked,
             "* hapus | # selesai");
}

void scanCard() {
  if (!rfidReady) return;
  if (!rfid.PICC_IsNewCardPresent()) {
    lastUid = "";
    return;
  }
  if (!rfid.PICC_ReadCardSerial()) return;

  String uid;
  for (byte i = 0; i < rfid.uid.size; ++i) {
    char part[3];
    snprintf(part, sizeof(part), "%02X", rfid.uid.uidByte[i]);
    uid += part;
  }

  if (uid != lastUid) {
    lastUid = uid;
    Serial.print("RC522 UID: ");
    Serial.println(uid);
    drawScreen("RC522: CARD OK", "UID:", uid, "Lepas kartu utk ulang");
  }
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Wire.begin(OLED_SDA, OLED_SCL);

  oledReady = display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS);
  if (oledReady) {
    display.clearDisplay();
    display.display();
    drawScreen("CASHIER HARDWARE", "OLED SSD1306 OK", "Starting RC522...");
  } else {
    Serial.println("ERROR: SSD1306 not found at I2C 0x3C");
  }

  SPI.begin(RFID_SCK, RFID_MISO, RFID_MOSI, RFID_SS);
  rfid.PCD_Init();
  delay(50);
  byte version = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  rfidReady = version != 0x00 && version != 0xFF;
  Serial.printf("RC522 VersionReg: 0x%02X (%s)\n",
                version, rfidReady ? "OK" : "NOT FOUND");

  if (oledReady) {
    drawScreen("CASHIER HARDWARE", "OLED: OK", rfidReady ? "RC522: OK" : "RC522: ERROR",
               "Tekan tombol keypad");
  }
  Serial.println("Hardware test ready. Keys: 0-9, *=backspace, #=confirm, A-D=control.");
}

void loop() {
  const char key = keypad.getKey();
  if (key) {
    Serial.printf("KEY: %c\n", key);
    if (key >= '0' && key <= '9' && typed.length() < 16) {
      typed += key;
      showInput();
    } else if (key == '*' && typed.length()) {
      typed.remove(typed.length() - 1);
      showInput();
    } else if (key == '#') {
      Serial.print("KEYPAD CONFIRMED: ");
      Serial.println(typed);
      drawScreen("KEYPAD: CONFIRMED", "Jumlah digit: " + String(typed.length()),
                 "Input: " + typed, "Tekan angka utk reset");
      typed = "";
    } else if (key >= 'A' && key <= 'D') {
      drawScreen("KEYPAD CONTROL", String("Tombol: ") + key, "Matriks 4x4 OK", "Tekan angka utk input");
    }
  }

  scanCard();

  if (millis() - lastScreenUpdate > 15000UL) {
    lastScreenUpdate = millis();
    if (!typed.length()) {
      drawScreen("M-GROUP CASHIER", oledReady ? "OLED SSD1306: OK" : "OLED: ERROR",
                 rfidReady ? "RC522: READY" : "RC522: ERROR",
                 "Tap kartu / tekan key");
    }
  }
  delay(10);
}
