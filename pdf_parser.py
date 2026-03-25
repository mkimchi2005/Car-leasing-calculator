"""
ניתוח PDF של תלוש שכר ישראלי.
אסטרטגיה שלושה-שלבים:
  1. חיפוש keyword + מספר סמוך בטקסט הגולמי
  2. חיפוש בטבלאות שמחלץ pdfplumber
  3. fallback: raw text + טופס ידני
"""
from __future__ import annotations
import io
import re
import unicodedata

import pdfplumber

from models import ParseResult, SalaryData

# ─── מילות מפתח לכל שדה ──────────────────────────────────────────────────
FIELD_PATTERNS: dict[str, list[str]] = {
    "gross": [
        r"שכר\s*ברוטו", r"ברוטו\s*לתשלום", r"סה[\"״]כ\s*ברוטו",
        r"שכר\s*כולל", r"שכר\s*חודשי\s*ברוטו",
    ],
    "income_tax": [
        r"מס\s*הכנסה", r"ניכוי\s*מס\s*הכנסה",
    ],
    "national_insurance": [
        r"ביטוח\s*לאומי", r"ב\.?\s*לאומי", r"ביטל[\"״]א",
    ],
    "health_insurance": [
        r"ביטוח\s*בריאות", r"דמי\s*בריאות",
    ],
    "net_salary": [
        r"שכר\s*נטו", r"לתשלום\s*נטו", r"סה[\"״]כ\s*נטו", r"נטו\s*לתשלום",
        r"סכום\s*לתשלום",
    ],
    "credit_points": [
        r"נקודות?\s*זיכוי", r"נק[\"']?\s*זיכוי",
    ],
    "car_budget": [
        r"תקציב\s*רכב\s*אישי", r"תקציב\s*רכב", r"תקציב\s*ליסינג",
        r"תקציב\s*רכב\s*חודשי",
    ],
    "special_area_credit": [
        r"זיכוי\s*אזור\s*מיוחד", r"זיכוי\s*אזור", r"אזור\s*מיוחד",
        r"זיכוי\s*ישוב", r"זיכוי\s*יישוב",
    ],
}

# מספר: 1-7 ספרות + אופציונלי פסיקים + אופציונלי נקודה עם 2 ספרות
NUM_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d{1,7}(?:\.\d{1,2})?)\b")

# טווחים סבירים לכל שדה (min, max)
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "gross": (2_000, 200_000),
    "income_tax": (0, 100_000),
    "national_insurance": (0, 20_000),
    "health_insurance": (0, 10_000),
    "net_salary": (1_000, 200_000),
    "credit_points": (0.25, 20.0),
    "car_budget": (100, 10_000),
    "special_area_credit": (10, 5_000),
}


def _normalize_text(text: str) -> str:
    """מנרמל טקסט עברי: Unicode NFC, מסיר סימני RTL."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u200f", "").replace("\u200e", "").replace("\u200b", "")
    return text


def _parse_num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _find_in_text(text: str, field: str) -> float | None:
    """
    מחפש keyword ואז מחפש מספר סמוך (עד 120 תווים).
    מסנן לפי טווח סביר.
    """
    patterns = FIELD_PATTERNS[field]
    lo, hi = PLAUSIBLE_RANGES[field]

    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            start = m.start()
            end = m.end()
            # חפש מספר בחלון של 120 תווים לפני ואחרי
            window_before = text[max(0, start - 120): start]
            window_after = text[end: end + 120]

            candidates: list[float] = []
            for window in [window_after, window_before]:
                for nm in NUM_RE.finditer(window):
                    val = _parse_num(nm.group())
                    if val is not None and lo <= val <= hi:
                        candidates.append(val)

            if candidates:
                # עדיפות לאחרי ה-keyword; בוחרים את הגדול ביותר בחלון "אחרי"
                after_candidates = []
                for nm in NUM_RE.finditer(window_after):
                    val = _parse_num(nm.group())
                    if val is not None and lo <= val <= hi:
                        after_candidates.append(val)
                if after_candidates:
                    return after_candidates[0]
                return candidates[0]
    return None


def _find_in_tables(tables: list[list[list[str | None]]], field: str) -> float | None:
    """
    מחפש שדה בטבלאות שחולץ pdfplumber.
    מחפש תא שמכיל keyword ואז בודק תאים סמוכים באותה שורה.
    """
    patterns = FIELD_PATTERNS[field]
    lo, hi = PLAUSIBLE_RANGES[field]

    for table in tables:
        for row in table:
            row_strs = [str(c).strip() if c else "" for c in row]
            for i, cell in enumerate(row_strs):
                cell_norm = _normalize_text(cell)
                for pat in patterns:
                    if re.search(pat, cell_norm, re.IGNORECASE):
                        # בדוק תאים סמוכים (לפני ואחרי) באותה שורה
                        neighbors = row_strs[:i] + row_strs[i + 1:]
                        for n in neighbors:
                            val = _parse_num(n.replace(",", "").replace("₪", "").strip())
                            if val is not None and lo <= val <= hi:
                                return val
    return None


def parse_paystub(file_bytes: bytes) -> ParseResult:
    """
    מנתח PDF של תלוש שכר.
    מחזיר ParseResult עם נתוני שכר (אם הצליח) או raw text (אם נכשל).
    """
    warnings: list[str] = []

    try:
        pdf = pdfplumber.open(io.BytesIO(file_bytes))
    except Exception as e:
        return ParseResult(
            success=False,
            raw_text=f"לא ניתן לפתוח את קובץ ה-PDF: {e}",
            warnings=["קובץ PDF פגום או לא תקין."],
        )

    all_text = ""
    all_tables: list[list[list[str | None]]] = []

    with pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            all_text += _normalize_text(page_text) + "\n"
            try:
                tables = page.extract_tables() or []
                all_tables.extend(tables)
            except Exception:
                pass

    if not all_text.strip():
        return ParseResult(
            success=False,
            raw_text="",
            warnings=["ה-PDF אינו מכיל טקסט (ייתכן שהוא קובץ סרוק). נא להזין נתונים ידנית."],
        )

    # ─── Pass 1: חיפוש בטקסט גולמי ────────────────────────────────────────
    extracted: dict[str, float | None] = {}
    for field in FIELD_PATTERNS:
        extracted[field] = _find_in_text(all_text, field)

    # ─── Pass 2: חיפוש בטבלאות ─────────────────────────────────────────────
    for field in FIELD_PATTERNS:
        if extracted[field] is None and all_tables:
            extracted[field] = _find_in_tables(all_tables, field)

    found_count = sum(1 for v in extracted.values() if v is not None)

    # ─── חישוב confidence (רק על שדות הליבה, לא על השדות האופציונליים) ──────
    CORE_FIELDS = {"gross", "income_tax", "national_insurance", "health_insurance", "net_salary", "credit_points"}
    core_found = sum(1 for f in CORE_FIELDS if extracted.get(f) is not None)
    confidence = (core_found / len(CORE_FIELDS)) * 0.7

    gross = extracted.get("gross")
    net = extracted.get("net_salary")
    income_tax = extracted.get("income_tax")
    ni = extracted.get("national_insurance")
    hi = extracted.get("health_insurance")
    credit_points = extracted.get("credit_points")
    car_budget = extracted.get("car_budget")
    special_area_credit = extracted.get("special_area_credit")

    # בדיקת עקביות: נטו ≈ ברוטו - סכום ניכויים
    if gross and net and income_tax and ni and hi:
        expected_net = gross - income_tax - ni - hi
        if abs(expected_net - net) / max(net, 1) < 0.10:
            confidence += 0.2
        else:
            warnings.append(
                f"אי-עקביות: ברוטו ({gross:,.0f}) - ניכויים ≠ נטו ({net:,.0f}). "
                "ייתכן שיש ניכויים נוספים בתלוש (פנסיה, קרן השתלמות וכו')."
            )

    if credit_points is not None:
        confidence += 0.1

    confidence = min(confidence, 1.0)

    if confidence < 0.4:
        warnings.append("לא ניתן לחלץ נתונים מספיקים מה-PDF. נא לבדוק ולעדכן ידנית.")

    # ─── בניית SalaryData ──────────────────────────────────────────────────
    salary_data: SalaryData | None = None
    if core_found >= 3 and gross is not None and net is not None:
        salary_data = SalaryData(
            gross=gross,
            income_tax_paid=income_tax or 0.0,
            ni_paid=ni or 0.0,
            hi_paid=hi or 0.0,
            net_salary=net,
            credit_points=credit_points if credit_points is not None else 2.25,
            car_budget=car_budget or 0.0,
            special_area_credit=special_area_credit or 0.0,
            source="parsed",
        )
        if credit_points is None:
            warnings.append(
                "נקודות הזיכוי לא נמצאו בתלוש. הוגדר ערך ברירת מחדל 2.25 — "
                "נא לעדכן לפי מספר הנקודות האמיתי שלך (כולל ילדים, יישוב מזכה וכו')."
            )
        if special_area_credit:
            warnings.append(
                f"זיכוי אזור מיוחד זוהה בתלוש: ₪{special_area_credit:,.0f}/חודש."
            )
        if car_budget:
            warnings.append(
                f"תקציב רכב אישי זוהה בתלוש: ₪{car_budget:,.0f}/חודש."
            )

    return ParseResult(
        success=salary_data is not None,
        data=salary_data,
        raw_text=all_text[:4000] if confidence < 0.5 else None,
        confidence=confidence,
        warnings=warnings,
    )
