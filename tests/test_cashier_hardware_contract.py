from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASHIER = (ROOT / "esp32" / "cashier" / "MGroupCashier.ino").read_text(encoding="utf-8")
READER = (ROOT / "esp32" / "cashier" / "MGroupCardReader.h").read_text(encoding="utf-8")
KEYPAD = (ROOT / "esp32" / "cashier" / "MGroupKeypad.h").read_text(encoding="utf-8")


def test_cashier_hardware_pin_map_is_locked():
    expected_cashier_pins = {
        "#define PN532_SDA 21",
        "#define PN532_SCL 22",
        "#define PN532_IRQ 39",
        "#define PN532_RESET 5",
        "#define RC522_SCK 18",
        "#define RC522_MISO 19",
        "#define RC522_MOSI 23",
        "#define RC522_SS 27",
        "#define RC522_RST 4",
    }
    for pin in expected_cashier_pins:
        assert pin in CASHIER

    assert "byte M_GROUPRowPins[M_GROUP_ROWS]={32,33,25,26};" in KEYPAD
    assert "byte M_GROUPColPins[M_GROUP_COLS]={13,14,16,17};" in KEYPAD


def test_reader_abstraction_has_both_supported_readers_and_safe_none_state():
    assert "M_GROUP_READER_PN532" in READER
    assert "M_GROUP_READER_RC522" in READER
    assert "M_GROUP_READER_NONE" in READER
    assert "pn532.getFirmwareVersion()" in READER
    assert "rc522.PCD_ReadRegister(MFRC522::VersionReg)" in READER
    assert "type = M_GROUP_READER_NONE;" in READER
    assert "if (type == M_GROUP_READER_NONE)" in READER


def test_reader_uid_buffer_and_keypad_feedback_contract():
    assert "M_GROUP_MAX_UID_LENGTH = 10" in READER
    assert "len = detectedLen > M_GROUP_MAX_UID_LENGTH ? M_GROUP_MAX_UID_LENGTH : detectedLen;" in READER
    assert "rc522.PICC_HaltA();" in READER
    assert "rc522.PCD_StopCrypto1();" in READER
    assert "lcdShow(\"NFC ERROR\",\"Cek koneksi\")" in CASHIER
    assert "lcdShow(\"NFC ERROR\",\"Cek reader\")" in CASHIER
    assert "if(k=='*'&&!s.isEmpty())" in CASHIER
    assert "else if(k=='#'&&s.length()>=minDigits)" in CASHIER


def test_cashier_uses_oled_and_formats_registration_uid_for_api():
    assert "#include <Adafruit_SSD1306.h>" in CASHIER
    assert "OLED_I2C_ADDRESS=0x3C" in CASHIER
    assert "display.begin(SSD1306_SWITCHCAPVCC,OLED_I2C_ADDRESS)" in CASHIER
    assert "LiquidCrystal_I2C" not in CASHIER
    assert "String uidToCardUid(const uint8_t* uid,uint8_t len)" in CASHIER
    assert "card_uid" in CASHIER
    assert "uidToCardUid(uid,len)" in CASHIER
    assert "bool waitForCardUID(uint8_t* uid,uint8_t& len,const char* prompt)" in CASHIER
    assert "millis()-scanStarted<20000UL" in CASHIER
    assert "if(!waitForCardUID(uid,len,\"Topup NFC\")) return;" in CASHIER
    assert "if(!waitForCardUID(uid,len,\"REGISTRASI NFC\")) return;" in CASHIER
    assert "while(!card.readUID(uid,len))" not in CASHIER
    assert "long bal=p>=0?reply.substring(p+16).toInt():0;" not in CASHIER
    assert "lcdShow(\"Saldo sisa\",\"Tidak tersedia\")" in CASHIER


def test_cashier_has_local_setup_webui_and_no_legacy_lcd_dependency():
    assert "#include <WebServer.h>" in CASHIER
    assert "void startConfigPortal()" in CASHIER
    assert 'configServer.on("/save",HTTP_POST' in CASHIER
    assert 'cashierPrefs.putString("server_url",M_GROUP_BASE_URL)' in CASHIER
    assert 'cashierPrefs.putString("device_key",M_GROUP_DEVICE_KEY)' in CASHIER
    assert 'if(!configured || forceSetup || M_GROUP_DEVICE_KEY.length()==0)' not in CASHIER
    assert "if(needsConfigPortal) startConfigPortal();" in CASHIER
    assert "#include <LiquidCrystal_I2C.h>" not in CASHIER
