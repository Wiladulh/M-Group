from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASHIER = (ROOT / "esp32" / "cashier" / "NvmCashier.ino").read_text(encoding="utf-8")
READER = (ROOT / "esp32" / "cashier" / "NvmCardReader.h").read_text(encoding="utf-8")
KEYPAD = (ROOT / "esp32" / "cashier" / "NvmKeypad.h").read_text(encoding="utf-8")


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

    assert "byte nvmRowPins[NVM_ROWS]={32,33,25,26};" in KEYPAD
    assert "byte nvmColPins[NVM_COLS]={13,14,16,17};" in KEYPAD


def test_reader_abstraction_has_both_supported_readers_and_safe_none_state():
    assert "NVM_READER_PN532" in READER
    assert "NVM_READER_RC522" in READER
    assert "NVM_READER_NONE" in READER
    assert "pn532.getFirmwareVersion()" in READER
    assert "rc522.PCD_ReadRegister(MFRC522::VersionReg)" in READER
    assert "type = NVM_READER_NONE;" in READER
    assert "if (type == NVM_READER_NONE)" in READER


def test_reader_uid_buffer_and_keypad_feedback_contract():
    assert "NVM_MAX_UID_LENGTH = 10" in READER
    assert "len = detectedLen > NVM_MAX_UID_LENGTH ? NVM_MAX_UID_LENGTH : detectedLen;" in READER
    assert "rc522.PICC_HaltA();" in READER
    assert "rc522.PCD_StopCrypto1();" in READER
    assert "lcdShow(\"NFC ERROR\",\"Cek koneksi\")" in CASHIER
    assert "lcdShow(\"NFC ERROR\",\"Cek reader\")" in CASHIER
    assert "if(k=='*'&&!s.isEmpty())" in CASHIER
    assert "else if(k=='#'&&s.length()>=minDigits)" in CASHIER
