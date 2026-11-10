from app.modules.docs_extract.validators import (
    validate_edrpou, validate_extraction, validate_iban, validate_ipn,
)


def test_ipn_checksum():
    # синтетичний валідний: перші 9 цифр 123456789 → контрольна
    d = "123456789"
    w = (-1, 5, 7, 9, 4, 6, 10, 5, 7)
    chk = sum(int(x) * y for x, y in zip(d, w)) % 11 % 10
    assert validate_ipn(d + str(chk))
    assert not validate_ipn(d + str((chk + 1) % 10))
    assert not validate_ipn("123")


def test_edrpou():
    assert validate_edrpou("32855961")  # відомий валідний код
    assert not validate_edrpou("32855962")
    assert not validate_edrpou("1234")


def test_iban():
    assert validate_iban("UA213223130000026007233566001")  # приклад із документації НБУ
    assert not validate_iban("UA213223130000026007233566002")
    assert not validate_iban("UA2132231300000260072335660")  # коротший за 29


def test_sum_mismatch_and_missing():
    flags = validate_extraction({
        "supplier_tax_id": "32855961", "total_amount": 100.0, "vat_amount": 0,
        "line_items": [{"description": "x", "quantity": 1, "unit_price": 50, "amount": 50}],
    })
    assert any(f["code"] == "sum_mismatch" for f in flags)
    assert any(f["code"] == "amount_missing" for f in validate_extraction({"supplier_tax_id": "32855961"}))


def test_vat_included_ok():
    flags = validate_extraction({
        "supplier_tax_id": "32855961", "total_amount": 120.0, "vat_amount": 20.0,
        "line_items": [{"description": "x", "quantity": 1, "unit_price": 100, "amount": 100}],
    })
    assert not any(f["code"] == "sum_mismatch" for f in flags)
