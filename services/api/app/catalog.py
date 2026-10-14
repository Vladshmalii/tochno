"""Каталог модулів платформи і тарифів за замовчуванням.

Модуль — одиниця функціоналу, яку можна підключити клієнту (через тариф або
індивідуальним override в адмінці)."""

MODULES = {
    "docs_extract": {
        "name": "Аналіз документів",
        "description": "Розпізнавання рахунків, актів, накладних: AI витягує поля, перевіряє реквізити, знаходить дублікати.",
        "ready": True,
    },
    "reconcile": {
        "name": "Звірка контрагентів",
        "description": "Довідник контрагентів, автозвірка за ІПН/ЄДРПОУ та назвою, контроль зміни IBAN.",
        "ready": True,
    },
    "reports": {
        "name": "Бухгалтерські звіти",
        "description": "Баланс, ОПУ, ОСВ, банківські виписки: нормалізація, показники, AI-резюме.",
        "ready": True,
    },
    "identity": {
        "name": "Кадри: документи особи",
        "description": "Паспорт, ID-картка, довідка ІПН: розпізнавання з валідацією контрольних сум.",
        "ready": True,
    },
    "knowledge": {
        "name": "База знань та AI-асистент",
        "description": "Чат-асистент за внутрішніми інструкціями компанії (RAG).",
        "ready": True,
    },
}

DEFAULT_PLANS = [
    {"code": "trial", "name": "Trial", "price_month": 0, "doc_limit_month": 30, "modules": ["docs_extract"]},
    {"code": "start", "name": "Start", "price_month": 49, "doc_limit_month": 300,
     "modules": ["docs_extract", "reconcile"]},
    {"code": "business", "name": "Business", "price_month": 199, "doc_limit_month": 3000,
     "modules": ["docs_extract", "reconcile", "reports", "identity", "knowledge"]},
    {"code": "enterprise", "name": "Enterprise", "price_month": 0, "doc_limit_month": 0,
     "modules": list(MODULES.keys())},
]
