"""Перевірки документів особи (паспорт, ID-картка, довідка ІПН): ІПН, MRZ ICAO 9303, номери."""

import re
from datetime import date, timedelta
from typing import Dict, Optional

from ..docs_extract.validators import validate_ipn

_IPN_EPOCH = date(1899, 12, 31)
_LATIN_TO_CYR = str.maketrans("ABCEHIKMOPTXY", "АВСЕНІКМОРТХУ")
_PASSPORT = re.compile(r"^[А-ЯІЇЄҐ]{2}\d{6}$")
_ID_CARD = re.compile(r"^\d{9}$")


def ipn_birth_date(tax_id: str) -> str:
    if not validate_ipn(tax_id):
        return ""
    d = re.sub(r"\D", "", tax_id)
    return (_IPN_EPOCH + timedelta(days=int(d[:5]))).isoformat()


def ipn_gender(tax_id: str) -> str:
    if not validate_ipn(tax_id):
        return ""
    return "чоловіча" if int(re.sub(r"\D", "", tax_id)[8]) % 2 else "жіноча"


def mrz_check_digit(field: str) -> int:
    total = 0
    for i, ch in enumerate(field):
        v = int(ch) if ch.isdigit() else (ord(ch) - 55 if "A" <= ch <= "Z" else 0)
        total += v * (7, 3, 1)[i % 3]
    return total % 10


def normalize_document_number(value: str) -> str:
    compact = re.sub(r"[\s\-№#]", "", (value or "").strip()).upper()
    if not compact:
        return ""
    m = re.fullmatch(r"IDUKR(\d{9})(\d)?", compact)
    if m:
        number, check = m.group(1), m.group(2)
        return number if check is None or mrz_check_digit(number) == int(check) else compact
    cyr = compact.translate(_LATIN_TO_CYR)
    return cyr if (_PASSPORT.match(cyr) or _ID_CARD.match(cyr)) else compact


def is_valid_document_number(value: str) -> bool:
    n = normalize_document_number(value)
    return bool(_PASSPORT.match(n) or _ID_CARD.match(n))


def _mrz_date(yymmdd: str, future: bool, today: date) -> str:
    try:
        yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
        century = 2000 if (future or yy <= today.year % 100) else 1900
        return date(century + yy, mm, dd).isoformat()
    except ValueError:
        return ""


def parse_td1_mrz(mrz: str, today: Optional[date] = None) -> Dict[str, str]:
    """Повертає ЛИШЕ поля, що пройшли контрольну цифру (надійніші за візуальне розпізнавання)."""
    ref = today or date.today()
    lines = [re.sub(r"\s", "", ln).upper() for ln in (mrz or "").splitlines() if ln.strip()]
    if len(lines) < 2 or len(lines[0]) < 15 or len(lines[1]) < 15:
        return {}
    l1, l2, out = lines[0], lines[1], {}
    if l1[14].isdigit() and mrz_check_digit(l1[5:14]) == int(l1[14]) and l1[5:14].replace("<", ""):
        out["document_number"] = l1[5:14].replace("<", "")
    if l2[6].isdigit() and mrz_check_digit(l2[0:6]) == int(l2[6]):
        b = _mrz_date(l2[0:6], False, ref)
        if b:
            out["birth_date"] = b
    if l2[7] in ("M", "F"):
        out["gender"] = "чоловіча" if l2[7] == "M" else "жіноча"
    if l2[14].isdigit() and mrz_check_digit(l2[8:14]) == int(l2[14]):
        e = _mrz_date(l2[8:14], True, ref)
        if e:
            out["expiry_date"] = e
    return out


def plausible_birth_date(value: str, min_age: int = 14, max_age: int = 100, today: Optional[date] = None) -> bool:
    try:
        y, m, d = (int(x) for x in value.split("-"))
        born = date(y, m, d)
    except (ValueError, AttributeError):
        return False
    ref = today or date.today()
    if born > ref:
        return False
    age = ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))
    return min_age <= age <= max_age
