"""
ניתוח קובץ Excel עם רשימת רכבי ליסינג.
תומך בשמות עמודות שונים (עברי ואנגלי).
"""
from __future__ import annotations
import io
import re

import pandas as pd

from models import CarOption

# aliases לכל עמודה – חיפוש case-insensitive
CAR_NAME_ALIASES = [
    "שם רכב", "רכב", "דגם", "model", "car", "שם", "מכונית", "סוג רכב",
    "תיאור", "description", "vehicle", "type", "קטגוריה",
]
# עמודת שם הדגם — תחובר לשם היצרן אם שתיהן קיימות
MODEL_NAME_ALIASES = [
    "שם הדגם", "שם דגם", "דגם", "model name", "trim", "גרסה", "variant",
]
# עמודת יצרן/מותג — תחובר לשם הדגם
MANUFACTURER_ALIASES = [
    "יצרן", "מותג", "מפיק", "manufacturer", "brand", "make",
]
EMPLOYEE_COST_ALIASES = [
    "עלות לעובד", "עלות עובד", "השתתפות עובד", "תשלום עובד",
    "employee cost", "monthly cost", "עלות חודשית", "חלק עובד",
    "השתתפות", "השתתפות ב", "per month", "תשלום", "תשלום חודשי",
    "מחיר לעובד", "עובד", "עלות ע",
]
BENEFIT_VALUE_ALIASES = [
    "שווי שימוש", "שווי", "benefit", "benefit value", "שווי שימוש חודשי",
    "שווי חודשי", 'ש"ש', "ש.ש", "שווי שי", "scale", "book of scale",
    "taxable", "imputed",
]


def _normalize(text: str) -> str:
    """מנרמל טקסט להשוואה: lowercase, ללא רווחים כפולים."""
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _matches_aliases(cell_text: str, aliases: list[str]) -> bool:
    norm = _normalize(cell_text)
    return any(_normalize(a) in norm or norm in _normalize(a) for a in aliases)


def _find_header_row(df: pd.DataFrame) -> int:
    """
    מאתר את שורת הכותרת (עד שורה 20) לפי התאמה לאליאסים.
    בוחר את השורה עם הכי הרבה התאמות (ולא פחות מ-1).
    """
    best_row = 0
    best_score = 0
    for i in range(min(20, len(df))):
        row = df.iloc[i].fillna("").astype(str)
        matches = 0
        for cell in row:
            for aliases in [CAR_NAME_ALIASES, EMPLOYEE_COST_ALIASES, BENEFIT_VALUE_ALIASES]:
                if _matches_aliases(cell, aliases):
                    matches += 1
                    break  # כל תא נחשב פעם אחת
        if matches > best_score:
            best_score = matches
            best_row = i
    return best_row


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    """מחזיר את שם העמודה הראשון שמתאים לאחד מה-aliases."""
    for col in columns:
        if _matches_aliases(str(col), aliases):
            return col
    return None


def _parse_number(val) -> float | None:
    """ממיר ערך לסכום כספי – מוריד פסיקים, ₪, רווחים."""
    if pd.isna(val):
        return None
    s = re.sub(r"[₪,\s]", "", str(val)).strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_leasing_excel(file_bytes: bytes) -> list[CarOption]:
    """
    מנתח קובץ Excel עם רשימת רכבי ליסינג.
    מחזיר רשימת CarOption.
    זורק ValueError אם לא נמצאו עמודות הכרחיות.
    """
    try:
        df_raw = pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=str)
    except Exception as e:
        raise ValueError(f"לא ניתן לפתוח את קובץ ה-Excel: {e}")

    header_row = _find_header_row(df_raw)

    # קריאה מחדש עם header נכון
    df = pd.read_excel(
        io.BytesIO(file_bytes),
        header=header_row,
        dtype=str,
    )
    df.columns = [str(c).strip() for c in df.columns]

    cols = df.columns.tolist()
    name_col        = _find_column(cols, CAR_NAME_ALIASES)
    model_name_col  = _find_column(cols, MODEL_NAME_ALIASES)
    manufacturer_col = _find_column(cols, MANUFACTURER_ALIASES)
    cost_col        = _find_column(cols, EMPLOYEE_COST_ALIASES)
    benefit_col     = _find_column(cols, BENEFIT_VALUE_ALIASES)

    # אם אין עמודת "שם רכב" כללית — ננסה לבנות שם מ-יצרן + דגם
    if name_col is None and (manufacturer_col or model_name_col):
        name_col = None  # ייבנה מתוך שילוב בלולאה

    missing = []
    if name_col is None and manufacturer_col is None and model_name_col is None:
        missing.append("שם רכב / יצרן / שם הדגם")
    if cost_col is None:
        missing.append("עלות לעובד")
    if benefit_col is None:
        missing.append("שווי שימוש")

    if missing:
        raise ValueError(
            f"לא נמצאו עמודות: {', '.join(missing)}. "
            "ודא שהקובץ מכיל כותרות כגון: שם רכב, עלות לעובד, שווי שימוש."
        )

    cars: list[CarOption] = []
    for _, row in df.iterrows():
        # בניית שם הרכב: יצרן + שם הדגם אם יש שתיהן; אחרת מה שנמצא
        parts = []
        if manufacturer_col:
            mfr = str(row[manufacturer_col]).strip()
            if mfr and mfr.lower() not in ("nan", "none", ""):
                parts.append(mfr)
        if model_name_col and model_name_col != manufacturer_col:
            mdl = str(row[model_name_col]).strip()
            if mdl and mdl.lower() not in ("nan", "none", ""):
                parts.append(mdl)
        if name_col and not parts:
            base = str(row[name_col]).strip()
            if base and base.lower() not in ("nan", "none", ""):
                parts.append(base)
        elif name_col and parts:
            # יש כבר יצרן/דגם — אם שם הרכב שונה מהם, הוסף אותו
            base = str(row[name_col]).strip()
            if base and base.lower() not in ("nan", "none", "") and base not in parts:
                parts.append(base)

        name = " ".join(parts).strip()
        if not name:
            continue

        cost = _parse_number(row[cost_col])
        benefit = _parse_number(row[benefit_col])

        if cost is None or benefit is None:
            continue  # שורה לא תקינה – מדלגים

        cars.append(CarOption(
            name=name,
            employee_monthly_cost=cost,
            benefit_value=benefit,
        ))

    if not cars:
        raise ValueError("לא נמצאו שורות תקינות בקובץ ה-Excel.")

    return cars


def get_excel_columns(file_bytes: bytes) -> list[str]:
    """מחזיר את שמות כל העמודות בקובץ (לצורך דיבוג)."""
    try:
        df_raw = pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=str)
        header_row = _find_header_row(df_raw)
        df = pd.read_excel(io.BytesIO(file_bytes), header=header_row, dtype=str)
        return [str(c).strip() for c in df.columns if str(c).strip() not in ("", "nan")]
    except Exception:
        return []
