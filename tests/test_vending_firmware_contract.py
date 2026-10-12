from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = (ROOT / "esp32" / "vending" / "NvmVending.ino").read_text(encoding="utf-8")


def test_vending_create_request_is_persisted_before_network_call():
    scan = FIRMWARE.index("savePendingCreateRequest(x.id,credential,vendingSequence,x.servo_channel);")
    send = FIRMWARE.index("String tx=beginTransaction(pendingCreateProduct,pendingCreateCredential,String(pendingCreateSequence));", scan)
    assert scan < send
    assert 'vendingPrefs.putBool("create_pending",true);' in FIRMWARE
    assert 'vendingPrefs.putString("create_product",product);' in FIRMWARE
    assert 'vendingPrefs.putString("create_credential",credential);' in FIRMWARE
    assert 'vendingPrefs.putULong("create_seq",seq);' in FIRMWARE


def test_vending_retries_pending_create_with_original_idempotency_sequence():
    assert 'pendingCreateSequence=vendingPrefs.getULong("create_seq",0);' in FIRMWARE
    assert 'beginTransaction(pendingCreateProduct,pendingCreateCredential,String(pendingCreateSequence))' in FIRMWARE
    assert 'showMessage("CREATE PENDING","Retry same request");' in FIRMWARE
    assert 'clearPendingCreateRequest();\n  savePendingTransaction(tx,"created",x.servo_channel);' in FIRMWARE
