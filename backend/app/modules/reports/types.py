"""Бухгалтерські звіти: банківська виписка, баланс, звіт про фінансові результати.

AI витягує таблиці, а всі показники рахує код — детерміновано, з перевіркою
внутрішньої узгодженості (баланс сходиться, сума рухів = зміна залишку тощо)."""

import re
import statistics
from collections import defaultdict
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from ..registry import Analysis, B, DocType, N, S, arr, desc, enum, register

MODULE = "reports"

CATEGORIES = [
    ("Зарплата", ("заробітн", "зарплат", "аванс", "відпускн")),
    ("Податки та збори", ("податк", "пдв", "єдин", "єсв", "пдфо", "військов", "бюджет")),
    ("Оренда", ("оренд",)),
    ("Комунальні та зв'язок", ("комунал", "електроенерг", "газопостач", "водопостач", "інтернет", "зв'язк", "зв’язк")),
    ("Банківські комісії", ("комісі", "банківськ", "обслуговування рахунку")),
    ("Власні перекази", ("між власними", "власних рахунк", "поповнення рахунку")),
]
_FLOAT = r"-?\d[\d\s ]*[.,]\d{2}"


def _flag(code: str, sev: str, field: str, msg: str) -> dict:
    return {"code": code, "severity": sev, "field": field, "message": msg}


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(x: float, cur: str = "") -> str:
    return f"{x:,.2f}".replace(",", " ") + (f" {cur}" if cur else "")


def categorize(description: str, amount: float) -> str:
    if amount > 0:
        return "Надходження"
    low = (description or "").lower()
    for name, keys in CATEGORIES:
        if any(k in low for k in keys):
            return name
    return "Інші витрати"


# --------------------------- банківська виписка ---------------------------

BANK_PROPS = {
    "bank_name": desc(S, "Назва банку"),
    "account_iban": desc(S, "IBAN рахунку"),
    "holder": desc(S, "Власник рахунку"),
    "period_from": desc(S, "Початок періоду, РРРР-ММ-ДД"),
    "period_to": desc(S, "Кінець періоду, РРРР-ММ-ДД"),
    "currency": desc(S, "Валюта"),
    "opening_balance": desc(N, "Залишок на початок періоду"),
    "closing_balance": desc(N, "Залишок на кінець періоду"),
    "transactions": arr({
        "date": desc(S, "Дата, РРРР-ММ-ДД"), "description": desc(S, "Призначення платежу"),
        "counterparty": desc(S, "Контрагент"),
        "amount": desc(N, "Сума зі знаком: надходження +, списання −"),
    }, "Усі операції виписки"),
    "confidence": enum(["high", "medium", "low"]),
    "notes": desc(S, "Коментарі українською"),
}
BANK_FIELDS = [
    {"key": "holder", "label": "Власник рахунку", "type": "text"},
    {"key": "bank_name", "label": "Банк", "type": "text"},
    {"key": "account_iban", "label": "IBAN", "type": "text"},
    {"key": "period_from", "label": "Період з", "type": "date"},
    {"key": "period_to", "label": "Період по", "type": "date"},
    {"key": "currency", "label": "Валюта", "type": "text"},
    {"key": "opening_balance", "label": "Залишок на початок", "type": "number"},
    {"key": "closing_balance", "label": "Залишок на кінець", "type": "number"},
]
BANK_PROMPT = (
    "Ви — асистент бухгалтера. Витягніть із банківської виписки всі операції. Суми зі знаком: надходження додатні, "
    "списання від'ємні. Не пропускайте й не вигадуйте рядків. Дати — РРРР-ММ-ДД. Коментарі — українською."
)


def analyze_bank(db: Session, doc, data: Dict[str, Any]) -> Analysis:
    d = dict(data)
    cur = (d.get("currency") or "UAH").upper()
    d["currency"] = cur
    tx: List[dict] = [t for t in (d.get("transactions") or [])]
    flags: List[dict] = []
    for t in tx:
        t["amount"] = _f(t.get("amount"))
        t["category"] = categorize(t.get("description", ""), t["amount"])
    d["transactions"] = tx
    inc = round(sum(t["amount"] for t in tx if t["amount"] > 0), 2)
    out = round(-sum(t["amount"] for t in tx if t["amount"] < 0), 2)
    opening, closing = _f(d.get("opening_balance")), _f(d.get("closing_balance"))

    if tx and (opening or closing) and abs(opening + inc - out - closing) > 0.05:
        flags.append(_flag("balance_mismatch", "error", "closing_balance",
                           f"Залишок на початок ({_money(opening)}) + рухи ({_money(inc - out)}) ≠ залишок на кінець "
                           f"({_money(closing)}): можливо, пропущені операції"))
    if not tx:
        flags.append(_flag("no_transactions", "error", "transactions", "Операцій не знайдено"))

    seen: Dict[tuple, int] = defaultdict(int)
    for t in tx:
        seen[(t.get("date"), t["amount"], (t.get("description") or "").strip().lower())] += 1
    dups = [k for k, v in seen.items() if v > 1]
    if dups:
        flags.append(_flag("duplicate_tx", "warning", "transactions",
                           f"Знайдено {len(dups)} можливих дублікатів операцій (однакові дата, сума, призначення)"))
    amounts = [abs(t["amount"]) for t in tx if t["amount"]]
    if len(amounts) >= 8:
        med = statistics.median(amounts)
        big = [t for t in tx if med and abs(t["amount"]) > 10 * med]
        if big:
            flags.append(_flag("outlier_tx", "info", "transactions",
                               f"{len(big)} операцій більш ніж у 10 разів перевищують медіану — перевірте"))

    by_cat: Dict[str, float] = defaultdict(float)
    by_cp: Dict[str, float] = defaultdict(float)
    for t in tx:
        if t["amount"] < 0:
            by_cat[t["category"]] += -t["amount"]
            if t.get("counterparty"):
                by_cp[t["counterparty"]] += -t["amount"]
    series, bal = [], opening
    for day in sorted({t.get("date") for t in tx if t.get("date")}):
        bal += sum(t["amount"] for t in tx if t.get("date") == day)
        series.append({"date": day, "balance": round(bal, 2)})
    metrics = {
        "kind": "bank_statement", "currency": cur, "total_in": inc, "total_out": out, "net": round(inc - out, 2),
        "count": len(tx), "opening": opening, "closing": closing,
        "by_category": [{"name": k, "amount": round(v, 2)} for k, v in sorted(by_cat.items(), key=lambda x: -x[1])],
        "top_counterparties": [{"name": k, "amount": round(v, 2)} for k, v in sorted(by_cp.items(), key=lambda x: -x[1])[:5]],
        "balance_series": series,
    }
    top = metrics["by_category"][0] if metrics["by_category"] else None
    metrics["summary"] = (
        f"За період {d.get('period_from') or '?'} — {d.get('period_to') or '?'}: {len(tx)} операцій, надходження "
        f"{_money(inc, cur)}, витрати {_money(out, cur)}, чистий рух {_money(inc - out, cur)}."
        + (f" Найбільша стаття витрат — «{top['name']}» ({_money(top['amount'], cur)})." if top else "")
    )
    return Analysis(data=d, flags=flags, metrics=metrics)


def _norm_date(s: str) -> str:
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else s


def mock_bank(text: str) -> Dict[str, Any]:
    tx = []
    for line in text.splitlines():
        m = re.match(rf"\s*(\d{{4}}-\d{{2}}-\d{{2}}|\d{{2}}\.\d{{2}}\.\d{{4}})[\s|;,]+(.+?)[\s|;,]+({_FLOAT})\s*$", line)
        if m:
            tx.append({"date": _norm_date(m.group(1)), "description": m.group(2).strip(), "counterparty": "",
                       "amount": float(re.sub(r"[\s ]", "", m.group(3)).replace(",", "."))})
    if not tx:
        tx = [{"date": "2026-01-05", "description": "Оплата за товар", "counterparty": "ТОВ Клієнт", "amount": 50000.0},
              {"date": "2026-01-10", "description": "Орендна плата", "counterparty": "ФОП Орендодавець", "amount": -12000.0},
              {"date": "2026-01-15", "description": "Заробітна плата", "counterparty": "", "amount": -20000.0}]
    net = round(sum(t["amount"] for t in tx), 2)
    dates = sorted(t["date"] for t in tx)
    return {"bank_name": "Демо-банк", "account_iban": "", "holder": "ТОВ «Демо»", "period_from": dates[0],
            "period_to": dates[-1], "currency": "UAH", "opening_balance": 0.0, "closing_balance": net,
            "transactions": tx, "confidence": "medium", "notes": "Демо-режим: LLM_PROVIDER=mock."}


# ------------------------------- баланс --------------------------------

_LINE = {"name": S, "amount": N, "current": desc(B, "true — поточні (оборотні) статті, false — довгострокові")}
BAL_PROPS = {
    "company": desc(S, "Підприємство"),
    "balance_date": desc(S, "Дата балансу, РРРР-ММ-ДД"),
    "currency": desc(S, "Валюта"),
    "assets": arr(_LINE, "Статті активу"),
    "liabilities": arr(_LINE, "Статті зобов'язань"),
    "equity": arr({"name": S, "amount": N}, "Статті власного капіталу"),
    "total_assets": desc(N, "Підсумок активу, як вказано в документі"),
    "total_liabilities_and_equity": desc(N, "Підсумок пасиву, як вказано в документі"),
    "confidence": enum(["high", "medium", "low"]),
    "notes": desc(S, "Коментарі українською"),
}
BAL_FIELDS = [
    {"key": "company", "label": "Підприємство", "type": "text"},
    {"key": "balance_date", "label": "Дата балансу", "type": "date"},
    {"key": "currency", "label": "Валюта", "type": "text"},
    {"key": "total_assets", "label": "Підсумок активу", "type": "number"},
    {"key": "total_liabilities_and_equity", "label": "Підсумок пасиву", "type": "number"},
]
BAL_PROMPT = (
    "Ви — фінансовий аналітик. Витягніть баланс (звіт про фінансовий стан): статті активу, зобов'язань і власного "
    "капіталу з сумами. Для активів і зобов'язань вкажіть current=true для поточних статей. Підсумки перепишіть як у "
    "документі, не рахуйте самі. Коментарі — українською."
)


def analyze_balance(db: Session, doc, data: Dict[str, Any]) -> Analysis:
    d = dict(data)
    cur = (d.get("currency") or "UAH").upper()
    d["currency"] = cur
    flags: List[dict] = []
    A, L, E = (d.get(k) or [] for k in ("assets", "liabilities", "equity"))
    sa, sl, se = (round(sum(_f(i.get("amount")) for i in x), 2) for x in (A, L, E))
    ca = round(sum(_f(i.get("amount")) for i in A if i.get("current")), 2)
    cl = round(sum(_f(i.get("amount")) for i in L if i.get("current")), 2)
    if abs(sa - (sl + se)) > 0.05:
        flags.append(_flag("balance_not_equal", "error", "total_assets",
                           f"Актив ({_money(sa)}) ≠ пасив ({_money(sl + se)}): баланс не сходиться на {_money(abs(sa - sl - se))}"))
    ta, tp = _f(d.get("total_assets")), _f(d.get("total_liabilities_and_equity"))
    if ta and abs(ta - sa) > 0.05:
        flags.append(_flag("assets_total_mismatch", "warning", "total_assets",
                           f"Підсумок активу в документі ({_money(ta)}) ≠ сума статей ({_money(sa)})"))
    if tp and abs(tp - (sl + se)) > 0.05:
        flags.append(_flag("liab_total_mismatch", "warning", "total_liabilities_and_equity",
                           f"Підсумок пасиву в документі ({_money(tp)}) ≠ сума статей ({_money(sl + se)})"))
    if se < 0:
        flags.append(_flag("negative_equity", "warning", "equity", "Власний капітал від'ємний"))
    ratio = lambda a, b: round(a / b, 2) if b else None  # noqa: E731
    metrics = {
        "kind": "balance_sheet", "currency": cur, "assets": sa, "liabilities": sl, "equity": se,
        "current_assets": ca, "current_liabilities": cl, "working_capital": round(ca - cl, 2),
        "current_ratio": ratio(ca, cl), "equity_ratio": ratio(se, sa), "debt_ratio": ratio(sl, sa),
    }
    parts = [f"Валюта балансу {_money(sa, cur)}."]
    if metrics["current_ratio"] is not None:
        verdict = "достатня" if metrics["current_ratio"] >= 1.5 else "обмежена" if metrics["current_ratio"] >= 1 else "недостатня"
        parts.append(f"Коефіцієнт поточної ліквідності {metrics['current_ratio']} — ліквідність {verdict}.")
    if metrics["equity_ratio"] is not None:
        parts.append(f"Частка власного капіталу {metrics['equity_ratio'] * 100:.0f}%.")
    metrics["summary"] = " ".join(parts)
    return Analysis(data=d, flags=flags, metrics=metrics)


def mock_balance(text: str) -> Dict[str, Any]:
    return {"company": "ТОВ «Демо»", "balance_date": "2026-03-31", "currency": "UAH",
            "assets": [{"name": "Основні засоби", "amount": 400000.0, "current": False},
                       {"name": "Запаси", "amount": 200000.0, "current": True},
                       {"name": "Грошові кошти", "amount": 150000.0, "current": True}],
            "liabilities": [{"name": "Кредиторська заборгованість", "amount": 250000.0, "current": True},
                            {"name": "Довгостроковий кредит", "amount": 100000.0, "current": False}],
            "equity": [{"name": "Статутний капітал", "amount": 100000.0}, {"name": "Нерозподілений прибуток", "amount": 300000.0}],
            "total_assets": 750000.0, "total_liabilities_and_equity": 750000.0, "confidence": "medium",
            "notes": "Демо-режим: LLM_PROVIDER=mock."}


# ------------------------- звіт про фін. результати -------------------------

PNL_PROPS = {
    "company": desc(S, "Підприємство"),
    "period_from": desc(S, "Початок періоду, РРРР-ММ-ДД"),
    "period_to": desc(S, "Кінець періоду, РРРР-ММ-ДД"),
    "currency": desc(S, "Валюта"),
    "revenue": desc(N, "Чистий дохід від реалізації"),
    "cost_of_sales": desc(N, "Собівартість реалізації (додатне число)"),
    "operating_expenses": desc(N, "Операційні витрати (адмін., збут, інші; додатне число)"),
    "other_income": desc(N, "Інші доходи"),
    "other_expenses": desc(N, "Інші витрати (додатне число)"),
    "tax": desc(N, "Податок на прибуток (додатне число)"),
    "net_profit": desc(N, "Чистий прибуток/збиток, як вказано в документі (збиток від'ємний)"),
    "confidence": enum(["high", "medium", "low"]),
    "notes": desc(S, "Коментарі українською"),
}
PNL_FIELDS = [
    {"key": "company", "label": "Підприємство", "type": "text"},
    {"key": "period_from", "label": "Період з", "type": "date"},
    {"key": "period_to", "label": "Період по", "type": "date"},
    {"key": "currency", "label": "Валюта", "type": "text"},
    {"key": "revenue", "label": "Дохід", "type": "number"},
    {"key": "cost_of_sales", "label": "Собівартість", "type": "number"},
    {"key": "operating_expenses", "label": "Операційні витрати", "type": "number"},
    {"key": "other_income", "label": "Інші доходи", "type": "number"},
    {"key": "other_expenses", "label": "Інші витрати", "type": "number"},
    {"key": "tax", "label": "Податок на прибуток", "type": "number"},
    {"key": "net_profit", "label": "Чистий прибуток (в документі)", "type": "number"},
]
PNL_PROMPT = (
    "Ви — фінансовий аналітик. Витягніть показники звіту про фінансові результати. Витрати — додатними числами, "
    "збиток — від'ємним у net_profit. Не рахуйте самі: переписуйте значення з документа. Коментарі — українською."
)


def analyze_pnl(db: Session, doc, data: Dict[str, Any]) -> Analysis:
    d = dict(data)
    cur = (d.get("currency") or "UAH").upper()
    d["currency"] = cur
    flags: List[dict] = []
    rev, cogs, opex = _f(d.get("revenue")), _f(d.get("cost_of_sales")), _f(d.get("operating_expenses"))
    oi, oe, tax = _f(d.get("other_income")), _f(d.get("other_expenses")), _f(d.get("tax"))
    gross = rev - cogs
    op = gross - opex
    net = op + oi - oe - tax
    stated = _f(d.get("net_profit"))
    if rev <= 0:
        flags.append(_flag("no_revenue", "warning", "revenue", "Дохід не розпізнано або нульовий"))
    if (d.get("net_profit") is not None) and abs(net - stated) > 0.05 and rev:
        flags.append(_flag("net_mismatch", "error", "net_profit",
                           f"Розрахунковий результат ({_money(net)}) не збігається з вказаним ({_money(stated)}) — "
                           "перевірте окремі статті"))
    if net < 0:
        flags.append(_flag("loss", "info", "net_profit", "Підприємство отримало збиток за період"))
    pct = lambda x: round(x / rev * 100, 1) if rev else None  # noqa: E731
    metrics = {"kind": "income_statement", "currency": cur, "revenue": rev, "gross_profit": round(gross, 2),
               "operating_profit": round(op, 2), "net_profit_calc": round(net, 2),
               "gross_margin_pct": pct(gross), "operating_margin_pct": pct(op), "net_margin_pct": pct(net)}
    metrics["summary"] = (
        f"Дохід {_money(rev, cur)}, валовий прибуток {_money(gross, cur)}"
        + (f" (маржа {metrics['gross_margin_pct']}%)" if rev else "")
        + f", чистий результат {_money(net, cur)}" + (f" (рентабельність {metrics['net_margin_pct']}%)." if rev else ".")
    )
    return Analysis(data=d, flags=flags, metrics=metrics)


def mock_pnl(text: str) -> Dict[str, Any]:
    return {"company": "ТОВ «Демо»", "period_from": "2026-01-01", "period_to": "2026-03-31", "currency": "UAH",
            "revenue": 1000000.0, "cost_of_sales": 600000.0, "operating_expenses": 250000.0, "other_income": 5000.0,
            "other_expenses": 10000.0, "tax": 25000.0, "net_profit": 120000.0, "confidence": "medium",
            "notes": "Демо-режим: LLM_PROVIDER=mock."}


# ------------------------------ реєстрація -------------------------------

def _idx_bank(d: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": d.get("holder", ""), "tax_id": "", "number": f"{d.get('period_from', '')}—{d.get('period_to', '')}",
            "amount": _f(d.get("closing_balance"))}


def _idx_bal(d: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": d.get("company", ""), "tax_id": "", "number": d.get("balance_date", ""), "amount": _f(d.get("total_assets"))}


def _idx_pnl(d: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": d.get("company", ""), "tax_id": "", "number": f"{d.get('period_from', '')}—{d.get('period_to', '')}",
            "amount": _f(d.get("net_profit"))}


register(DocType("bank_statement", MODULE, "Банківська виписка", "Банківська виписка з операціями за період.",
                 BANK_PROPS, BANK_PROMPT, BANK_FIELDS, analyze_bank, _idx_bank, mock_bank, view="report"))
register(DocType("balance_sheet", MODULE, "Баланс", "Баланс (звіт про фінансовий стан).",
                 BAL_PROPS, BAL_PROMPT, BAL_FIELDS, analyze_balance, _idx_bal, mock_balance, view="report"))
register(DocType("income_statement", MODULE, "Звіт про фінансові результати", "Звіт про фінансові результати (ОПУ).",
                 PNL_PROPS, PNL_PROMPT, PNL_FIELDS, analyze_pnl, _idx_pnl, mock_pnl, view="report"))
