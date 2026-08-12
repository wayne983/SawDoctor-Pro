"""客戶維修報價的純計價規則。

本模組不讀寫資料庫，也不修改傳入的工單字典。
"""

from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Mapping


class UnsupportedDiameterError(ValueError):
    """外徑或生效日期沒有可套用的自動計價規則。"""


@dataclass(frozen=True)
class PriceRule:
    version_id: str
    effective_from: date
    od_min: int
    od_max: int
    grinding_price: int
    tooth_price: int
    fanban_price: int


@dataclass(frozen=True)
class QuoteLineDraft:
    blade_id: int
    customer: str
    brand_id: str
    od: str
    thickness: str
    teeth: str
    spec: str
    source_grind: str
    source_supp_teeth: str
    source_fanban: str
    grinding_qty: int
    grinding_unit: int
    tooth_qty: int
    tooth_unit: int
    fanban_qty: int
    fanban_unit: int
    included: bool = True
    note: str = ""

    @property
    def subtotal(self) -> int:
        return (
            self.grinding_qty * self.grinding_unit
            + self.tooth_qty * self.tooth_unit
            + self.fanban_qty * self.fanban_unit
        )


PRICE_RULES = (
    PriceRule("2026-08-13-v1", date(2026, 8, 13), 305, 305, 240, 150, 230),
    PriceRule("2026-08-13-v1", date(2026, 8, 13), 355, 355, 280, 150, 230),
    PriceRule("2026-08-13-v1", date(2026, 8, 13), 405, 455, 350, 150, 250),
)


def parse_nonnegative_int(value: Any) -> int:
    """將整數字串正規化；拒絕負數、小數、空值與布林值。"""
    if isinstance(value, bool):
        raise ValueError("價格與數量必須是非負整數")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        raise ValueError("價格與數量必須是非負整數")
    if number < 0:
        raise ValueError("價格與數量必須是非負整數")
    return number


def price_rule_for(od: Any, effective_on: date) -> PriceRule:
    diameter = parse_nonnegative_int(od)
    matches = [
        rule
        for rule in PRICE_RULES
        if rule.effective_from <= effective_on and rule.od_min <= diameter <= rule.od_max
    ]
    if not matches:
        raise UnsupportedDiameterError(f"外徑 {od!r} 在 {effective_on.isoformat()} 沒有自動計價規則")
    return max(matches, key=lambda rule: rule.effective_from)


def build_quote_line(blade: Mapping[str, Any], rule: PriceRule) -> QuoteLineDraft:
    """依工單來源資料與價目規則產生可手動調整的報價草稿。"""
    source_grind = str(blade["grind"])
    source_supp_teeth = str(blade["supp_teeth"])
    source_fanban = str(blade["fanban"])
    tooth_qty = parse_nonnegative_int(source_supp_teeth)
    grinding_qty = 1 if source_grind == "是" else 0
    fanban_qty = 1 if source_fanban == "是" else 0
    od = str(blade["od"])
    thickness = str(blade["thickness"])
    teeth = str(blade["teeth"])
    return QuoteLineDraft(
        blade_id=parse_nonnegative_int(blade["id"]),
        customer=str(blade["customer"]),
        brand_id=str(blade["brand_id"]),
        od=od,
        thickness=thickness,
        teeth=teeth,
        spec=f"{od} x {thickness} x {teeth}T",
        source_grind=source_grind,
        source_supp_teeth=source_supp_teeth,
        source_fanban=source_fanban,
        grinding_qty=grinding_qty,
        grinding_unit=rule.grinding_price if grinding_qty else 0,
        tooth_qty=tooth_qty,
        tooth_unit=rule.tooth_price if tooth_qty else 0,
        fanban_qty=fanban_qty,
        fanban_unit=rule.fanban_price if fanban_qty else 0,
    )


def apply_manual_quote(
    line: QuoteLineDraft,
    *,
    grinding_qty: Any | None = None,
    grinding_unit: Any | None = None,
    tooth_qty: Any | None = None,
    tooth_unit: Any | None = None,
    fanban_qty: Any | None = None,
    fanban_unit: Any | None = None,
    included: bool | None = None,
    note: str | None = None,
) -> QuoteLineDraft:
    """回傳人工調整後的草稿，不回寫來源工單。"""
    changes: dict[str, Any] = {}
    for field, value in {
        "grinding_qty": grinding_qty,
        "grinding_unit": grinding_unit,
        "tooth_qty": tooth_qty,
        "tooth_unit": tooth_unit,
        "fanban_qty": fanban_qty,
        "fanban_unit": fanban_unit,
    }.items():
        if value is not None:
            changes[field] = parse_nonnegative_int(value)
    if included is not None:
        if not isinstance(included, bool):
            raise ValueError("是否列入報價必須是布林值")
        changes["included"] = included
    if note is not None:
        changes["note"] = str(note)
    return replace(line, **changes)
