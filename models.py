from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class SalaryData(BaseModel):
    gross: float = Field(..., description="שכר ברוטו חודשי")
    income_tax_paid: float = Field(..., description="מס הכנסה בתלוש")
    ni_paid: float = Field(..., description="ביטוח לאומי בתלוש")
    hi_paid: float = Field(..., description="ביטוח בריאות בתלוש")
    net_salary: float = Field(..., description="שכר נטו בתלוש")
    credit_points: float = Field(2.25, description="נקודות זיכוי")
    car_budget: float = Field(0.0, description="תקציב רכב אישי חודשי מהמעסיק (₪)")
    special_area_credit: float = Field(0.0, description="זיכוי אזור מיוחד חודשי (₪) — מופחת ישירות ממס הכנסה")
    current_car_benefit: float = Field(0.0, description="שווי שימוש רכב נוכחי הכלול כבר בברוטו (₪) — לצורך השוואה מול המצב הנוכחי")
    source: Literal["parsed", "manual"] = "manual"


class CarOption(BaseModel):
    name: str
    employee_monthly_cost: float = Field(..., description="עלות לעובד בחודש (₪)")
    benefit_value: float = Field(..., description="שווי שימוש חודשי (₪)")


class TaxBreakdown(BaseModel):
    gross: float
    income_tax: float
    national_insurance: float
    health_insurance: float
    total_deductions: float
    net: float


class CarImpactResult(BaseModel):
    car_name: str
    employee_monthly_cost: float
    effective_employee_cost: float  # אחרי הפחתת תקציב רכב
    car_budget_used: float          # כמה מהתקציב מכסה
    benefit_value: float
    base_breakdown: TaxBreakdown
    new_breakdown: TaxBreakdown
    income_tax_delta: float
    ni_delta: float
    hi_delta: float
    total_tax_increase: float
    net_salary_delta: float       # שינוי סופי בנטו (שלילי = עולה כסף)
    final_net: float
    marginal_rate_used: float     # שיעור מס שולי שנגזר מהתלוש (אם שונה מהחישוב)


class CalculateRequest(BaseModel):
    salary: SalaryData
    cars: list[CarOption]


class ParseResult(BaseModel):
    success: bool
    data: SalaryData | None = None
    raw_text: str | None = None
    confidence: float = 0.0
    warnings: list[str] = []


class TaxValidation(BaseModel):
    calculated_tax: float
    actual_tax: float
    difference_pct: float
    is_valid: bool
    warning: str | None = None


class CalculateResponse(BaseModel):
    results: list[CarImpactResult]
    base_breakdown: TaxBreakdown
    tax_validation: TaxValidation
    used_marginal_fallback: bool = False
