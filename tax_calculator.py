"""
Israeli payroll tax calculator — 2025 rates.
Logic: שווי שימוש is taxable-only income (included in income-tax AND NI/HI bases,
but NOT paid as cash). Car-budget surplus is real cash added to gross.
Social deductions (pension etc.) are fixed regardless of car choice.

When annual_extra > 0 (bonus, options, etc.) the income-tax is computed on an
annual basis (monthly_taxable × 12 + annual_extra) and divided by 12, so that
the bonus's effect on the effective marginal rate is captured correctly.
"""

from dataclasses import dataclass, field

# ── 2025 monthly income-tax brackets ────────────────────────────────────────
BRACKETS = [
    (7_010,  0.10),
    (10_060, 0.14),
    (16_150, 0.20),
    (22_440, 0.31),
    (46_690, 0.35),
    (60_130, 0.47),
    (float("inf"), 0.50),
]
CREDIT_POINT_VALUE = 242          # ₪ per point per month  (2025)

# ── 2025 Bituach-Leumi + Health (employee share) ────────────────────────────
NI_THRESHOLD = 7_522
NI_MAX       = 50_695
NI_LO,  NI_HI  = 0.004, 0.07
HI_LO,  HI_HI  = 0.031, 0.05


# ── Core tax functions ───────────────────────────────────────────────────────

def income_tax(gross: float, credit_points: float,
               area_pct: float, area_annual_cap: float) -> float:
    """Monthly income tax after credit-points and special-area credit."""
    tax, prev = 0.0, 0.0
    for ceiling, rate in BRACKETS:
        if gross <= prev:
            break
        tax += (min(gross, ceiling) - prev) * rate
        prev = ceiling
    tax -= credit_points * CREDIT_POINT_VALUE
    if area_pct > 0:
        qualifying = min(gross, area_annual_cap / 12.0) if area_annual_cap > 0 else gross
        tax -= qualifying * area_pct / 100.0
    return max(0.0, tax)


def income_tax_annual(annual_gross: float, credit_points: float,
                      area_pct: float, area_annual_cap: float) -> float:
    """Annual income tax — uses annual-equivalent brackets (monthly × 12).
    The area-credit cap is already expressed annually so it is used as-is."""
    tax, prev = 0.0, 0.0
    for ceiling, rate in BRACKETS:
        annual_ceil = ceiling * 12 if ceiling != float("inf") else float("inf")
        if annual_gross <= prev:
            break
        tax += (min(annual_gross, annual_ceil) - prev) * rate
        prev = annual_ceil
    tax -= credit_points * CREDIT_POINT_VALUE * 12
    if area_pct > 0:
        qualifying = min(annual_gross, area_annual_cap) if area_annual_cap > 0 else annual_gross
        tax -= qualifying * area_pct / 100.0
    return max(0.0, tax)


def _eff_it(monthly_taxable: float, annual_extra: float,
            cp: float, ap: float, ac: float) -> float:
    """Effective monthly income-tax.
    When annual_extra > 0 the calculation is annual (to capture bonus bracket
    effects) and the result is divided by 12 for the monthly equivalent."""
    if annual_extra > 0:
        return income_tax_annual(monthly_taxable * 12 + annual_extra, cp, ap, ac) / 12
    return income_tax(monthly_taxable, cp, ap, ac)


def national_insurance(gross: float) -> float:
    g = min(gross, NI_MAX)
    if g <= NI_THRESHOLD:
        return g * NI_LO
    return NI_THRESHOLD * NI_LO + (g - NI_THRESHOLD) * NI_HI


def health_insurance(gross: float) -> float:
    g = min(gross, NI_MAX)
    if g <= NI_THRESHOLD:
        return g * HI_LO
    return NI_THRESHOLD * HI_LO + (g - NI_THRESHOLD) * HI_HI


def total_tax(gross: float, cp: float, ap: float, ac: float) -> float:
    return (income_tax(gross, cp, ap, ac)
            + national_insurance(gross)
            + health_insurance(gross))


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class SalaryInput:
    gross: float                    # base cash gross (NO car budget, NO benefit)
    income_tax_actual: float        # from pay-stub — for display / validation
    ni_actual: float
    health_actual: float
    social_deductions: float        # pension + provident — FIXED, unchanged by car
    net_actual: float               # actual take-home — ground truth
    credit_points: float
    area_credit_pct: float          # זיכוי ישוב מזכה — % of income
    area_credit_cap: float          # same credit — annual ceiling (₪)
    car_budget: float               # employer car allowance
    cur_car_benefit: float          # current car שווי שימוש (0 = no car)
    cur_car_cost: float             # current car employee cost (0 = no car)
    annual_extra: float = 0         # בונוס / אופציות / הכנסה שנתית נוספת (₪)


@dataclass
class CarOption:
    manufacturer: str
    model: str
    employee_cost: float
    benefit_value: float


@dataclass
class CarResult:
    manufacturer: str
    model: str
    employee_cost: float
    benefit_value: float
    taxable_gross: float
    it: float                       # income tax
    ni: float
    hi: float
    model_net: float                # model net (before adjustment)
    expected_net: float             # model_net + net_adjustment
    delta_vs_current: float         # vs actual pay-stub net
    it_delta: float                 # income-tax change vs current car
    ni_hi_delta: float              # NI+HI change vs current car
    budget_effect: float            # + surplus, − deficit


# ── Main calculation ─────────────────────────────────────────────────────────

def calculate_all(sal: SalaryInput, cars: list) -> dict:
    cp, ap, ac = sal.credit_points, sal.area_credit_pct, sal.area_credit_cap
    ae = sal.annual_extra

    def it(monthly_taxable: float) -> float:
        return _eff_it(monthly_taxable, ae, cp, ap, ac)

    # ── Current car model (to derive net_adjustment) ─────────────────────────
    cur_surplus   = max(0.0, sal.car_budget - sal.cur_car_cost)
    cur_deficit   = max(0.0, sal.cur_car_cost - sal.car_budget)
    cur_cash      = sal.gross + cur_surplus
    cur_taxable   = cur_cash + sal.cur_car_benefit
    cur_it        = it(cur_taxable)
    cur_ni        = national_insurance(cur_taxable)
    cur_hi        = health_insurance(cur_taxable)
    cur_model_net = (cur_cash - cur_it - cur_ni - cur_hi
                     - sal.social_deductions - cur_deficit)
    net_adj       = sal.net_actual - cur_model_net   # bridges model → reality

    # ── No-car baseline ───────────────────────────────────────────────────────
    nc_taxable    = sal.gross + sal.car_budget        # whole budget → taxable cash
    nc_it         = it(nc_taxable)
    nc_ni         = national_insurance(nc_taxable)
    nc_hi         = health_insurance(nc_taxable)
    nc_model_net  = (nc_taxable - nc_it - nc_ni - nc_hi - sal.social_deductions)
    nc_expected   = nc_model_net + net_adj

    # ── Per-car calculation ───────────────────────────────────────────────────
    results: list = []
    for car in cars:
        surplus   = max(0.0, sal.car_budget - car.employee_cost)
        deficit   = max(0.0, car.employee_cost - sal.car_budget)
        cash      = sal.gross + surplus
        taxable   = cash + car.benefit_value
        car_it    = it(taxable)
        ni        = national_insurance(taxable)
        hi        = health_insurance(taxable)
        model_net = cash - car_it - ni - hi - sal.social_deductions - deficit
        expected  = model_net + net_adj

        results.append(CarResult(
            manufacturer     = car.manufacturer,
            model            = car.model,
            employee_cost    = car.employee_cost,
            benefit_value    = car.benefit_value,
            taxable_gross    = taxable,
            it               = car_it,
            ni               = ni,
            hi               = hi,
            model_net        = model_net,
            expected_net     = expected,
            delta_vs_current = expected - sal.net_actual,
            it_delta         = car_it - cur_it,
            ni_hi_delta      = (ni + hi) - (cur_ni + cur_hi),
            budget_effect    = surplus - deficit,
        ))

    return dict(
        net_actual      = sal.net_actual,
        net_adjustment  = round(net_adj, 2),
        cur_taxable     = cur_taxable,
        cur_it          = round(cur_it, 2),
        cur_ni          = round(cur_ni, 2),
        cur_hi          = round(cur_hi, 2),
        no_car_expected = round(nc_expected, 2),
        no_car_delta    = round(nc_expected - sal.net_actual, 2),
        cars            = results,
    )
