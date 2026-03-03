"""
ASC 606 Revenue Recognition Analysis Engine
=============================================
Implements the five-step model per ASC 606 (Revenue from Contracts with Customers).
Handles software licenses, support/maintenance, Agent Workspace Builds (AWB),
and AI Governance License Add-ons with proper SSP allocation and recognition timing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------

class ProductType(str, Enum):
    LICENSE = "license"
    SUPPORT = "support"
    AWB = "awb"
    AI_GOVERNANCE = "ai_governance"
    CODER_PREMIUM = "coder_premium"


class RecognitionPattern(str, Enum):
    POINT_IN_TIME = "point_in_time"
    RATABLE = "ratable"
    USAGE_BASED = "usage_based"


class SSPEstimationApproach(str, Enum):
    HISTORICAL = "historical"
    CONTRACTUAL_RATE = "contractual_rate"
    ADJUSTED_MARKET_ASSESSMENT = "adjusted_market_assessment"
    EXPECTED_COST_PLUS_MARGIN = "expected_cost_plus_margin"
    RESIDUAL = "residual"


# Historical SSP split for traditional deals (before 12/31/2025)
TRADITIONAL_LICENSE_SPLIT = 0.20
TRADITIONAL_SUPPORT_SPLIT = 0.80
TRADITIONAL_CUTOFF_DATE = date(2025, 12, 31)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class LineItem:
    description: str
    quantity: int
    unit_price: float
    total: float
    product_type: str  # one of ProductType values

    def __post_init__(self) -> None:
        self.total = round(float(self.total), 2)
        self.unit_price = round(float(self.unit_price), 2)
        self.quantity = int(self.quantity)
        if self.product_type not in [pt.value for pt in ProductType]:
            raise ValueError(
                f"Invalid product_type '{self.product_type}'. "
                f"Must be one of: {[pt.value for pt in ProductType]}"
            )


@dataclass
class OrderForm:
    customer_name: str
    order_date: str  # ISO format YYYY-MM-DD
    contract_start: str
    contract_end: str
    total_contract_value: float  # TCV
    line_items: list[LineItem] = field(default_factory=list)
    payment_terms: str = ""
    renewal_terms: str = ""

    def __post_init__(self) -> None:
        self.total_contract_value = round(float(self.total_contract_value), 2)

    @property
    def order_date_parsed(self) -> date:
        return _parse_date(self.order_date)

    @property
    def contract_start_parsed(self) -> date:
        return _parse_date(self.contract_start)

    @property
    def contract_end_parsed(self) -> date:
        return _parse_date(self.contract_end)

    @property
    def contract_months(self) -> int:
        start = self.contract_start_parsed
        end = self.contract_end_parsed
        months = (end.year - start.year) * 12 + (end.month - start.month)
        if end.day >= start.day:
            months += 1  # inclusive of the final partial month
        return max(months, 1)

    @property
    def is_traditional_deal(self) -> bool:
        return self.order_date_parsed <= TRADITIONAL_CUTOFF_DATE

    @property
    def has_awb(self) -> bool:
        return any(li.product_type == ProductType.AWB.value for li in self.line_items)

    @property
    def has_ai_governance(self) -> bool:
        return any(
            li.product_type == ProductType.AI_GOVERNANCE.value for li in self.line_items
        )

    @property
    def has_coder_premium(self) -> bool:
        return any(li.product_type == ProductType.CODER_PREMIUM.value for li in self.line_items)


@dataclass
class PerformanceObligation:
    id: str
    description: str
    product_type: str
    is_distinct: bool
    recognition_pattern: str
    asc_reference: str
    rationale: str
    line_item_total: float  # sum of underlying line items

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "product_type": self.product_type,
            "is_distinct": self.is_distinct,
            "recognition_pattern": self.recognition_pattern,
            "asc_reference": self.asc_reference,
            "rationale": self.rationale,
            "line_item_total": round(self.line_item_total, 2),
        }


@dataclass
class SSPAllocation:
    obligation_id: str
    description: str
    product_type: str
    standalone_selling_price: float
    ssp_estimation_approach: str
    allocated_amount: float
    allocation_percentage: float
    asc_reference: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "obligation_id": self.obligation_id,
            "description": self.description,
            "product_type": self.product_type,
            "standalone_selling_price": round(self.standalone_selling_price, 2),
            "ssp_estimation_approach": self.ssp_estimation_approach,
            "allocated_amount": round(self.allocated_amount, 2),
            "allocation_percentage": round(self.allocation_percentage, 4),
            "asc_reference": self.asc_reference,
            "warnings": self.warnings,
        }


@dataclass
class RecognitionSchedule:
    obligation_id: str
    description: str
    product_type: str
    recognition_pattern: str
    allocated_amount: float
    recognition_start: str
    recognition_end: str
    monthly_schedule: list[dict]  # [{month: "YYYY-MM", amount: float}, ...]
    asc_reference: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "obligation_id": self.obligation_id,
            "description": self.description,
            "product_type": self.product_type,
            "recognition_pattern": self.recognition_pattern,
            "allocated_amount": round(self.allocated_amount, 2),
            "recognition_start": self.recognition_start,
            "recognition_end": self.recognition_end,
            "monthly_schedule": [
                {"month": m["month"], "amount": round(m["amount"], 2)}
                for m in self.monthly_schedule
            ],
            "asc_reference": self.asc_reference,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(val: str) -> date:
    """Parse an ISO-format date string into a date object."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {val!r}. Use YYYY-MM-DD format.")


def _month_range(start: date, end: date) -> list[str]:
    """Generate a list of 'YYYY-MM' strings from start through end (inclusive)."""
    months: list[str] = []
    current = start.replace(day=1)
    end_first = end.replace(day=1)
    while current <= end_first:
        months.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return months


# ---------------------------------------------------------------------------
# ASC 606 Analyzer
# ---------------------------------------------------------------------------

class ASC606Analyzer:
    """Implements the ASC 606 five-step revenue recognition model."""

    # ------------------------------------------------------------------
    # Step 2 — Identify Performance Obligations
    # ------------------------------------------------------------------
    def identify_performance_obligations(
        self, order: OrderForm
    ) -> list[PerformanceObligation]:
        """
        ASC 606-10-25-14 through 25-22: Identify distinct performance
        obligations within the contract.
        """
        obligations: list[PerformanceObligation] = []
        po_counter = 0

        # Group line items by product type
        grouped: dict[str, list[LineItem]] = {}
        for li in order.line_items:
            grouped.setdefault(li.product_type, []).append(li)

        for ptype, items in grouped.items():
            po_counter += 1
            total = round(sum(i.total for i in items), 2)
            desc_parts = [i.description for i in items]
            combined_desc = "; ".join(desc_parts)

            if ptype == ProductType.LICENSE.value:
                obligations.append(
                    PerformanceObligation(
                        id=f"PO-{po_counter:03d}",
                        description=f"Software License — {combined_desc}",
                        product_type=ptype,
                        is_distinct=True,
                        recognition_pattern=RecognitionPattern.POINT_IN_TIME.value,
                        asc_reference="ASC 606-10-25-14 through 25-22; ASC 606-10-55-54",
                        rationale=(
                            "Software license grants a right to use intellectual property "
                            "as it exists at a point in time. The customer can benefit from "
                            "the license on its own or with readily available resources "
                            "(capable of being distinct) and it is separately identifiable "
                            "from other promises in the contract (distinct within the "
                            "context of the contract)."
                        ),
                        line_item_total=total,
                    )
                )

            elif ptype == ProductType.SUPPORT.value:
                obligations.append(
                    PerformanceObligation(
                        id=f"PO-{po_counter:03d}",
                        description=f"Support & Maintenance — {combined_desc}",
                        product_type=ptype,
                        is_distinct=True,
                        recognition_pattern=RecognitionPattern.RATABLE.value,
                        asc_reference="ASC 606-10-25-14 through 25-22; ASC 606-10-55-18",
                        rationale=(
                            "Support and maintenance services represent a stand-ready "
                            "obligation to provide updates, bug fixes, and technical "
                            "support over the contract term. The customer simultaneously "
                            "receives and consumes the benefits (ASC 606-10-25-27a). "
                            "Revenue is recognized ratably (straight-line) as a faithful "
                            "depiction of the transfer of services."
                        ),
                        line_item_total=total,
                    )
                )

            elif ptype == ProductType.AWB.value:
                obligations.append(
                    PerformanceObligation(
                        id=f"PO-{po_counter:03d}",
                        description=f"Agent Workspace Builds (AWB) — {combined_desc}",
                        product_type=ptype,
                        is_distinct=True,
                        recognition_pattern=RecognitionPattern.USAGE_BASED.value,
                        asc_reference=(
                            "ASC 606-10-25-14 through 25-22; "
                            "ASC 606-10-32-40 (variable consideration); "
                            "ASC 606-10-55-65 (sales/usage-based royalties)"
                        ),
                        rationale=(
                            "AWB represents a distinct service where the customer "
                            "consumes agent workspace builds on a usage basis. "
                            "Consideration is variable and directly tied to usage. "
                            "Revenue is recognized as consumption occurs, subject to "
                            "the variable consideration constraint (ASC 606-10-32-11). "
                            "As a usage-based fee for a license of IP, the sales/usage-"
                            "based royalty exception under ASC 606-10-55-65 may apply."
                        ),
                        line_item_total=total,
                    )
                )

            elif ptype == ProductType.AI_GOVERNANCE.value:
                obligations.append(
                    PerformanceObligation(
                        id=f"PO-{po_counter:03d}",
                        description=f"AI Governance License Add-on — {combined_desc}",
                        product_type=ptype,
                        is_distinct=True,
                        recognition_pattern=RecognitionPattern.POINT_IN_TIME.value,
                        asc_reference=(
                            "ASC 606-10-25-14 through 25-22; ASC 606-10-55-54; "
                            "ASC 606-10-32-33 through 32-35 (SSP estimation)"
                        ),
                        rationale=(
                            "AI Governance License is a new product offering that "
                            "provides the customer a right to use AI governance "
                            "functionality. As a distinct license of IP, recognition "
                            "is point-in-time if perpetual or ratable if term-based. "
                            "CRITICAL: This is a new product with no historical SSP — "
                            "requires estimation approach per ASC 606-10-32-33."
                        ),
                        line_item_total=total,
                    )
                )

            elif ptype == ProductType.CODER_PREMIUM.value:
                # Coder Premium is a bundled product — decompose into
                # License (20%) and Support (80%) performance obligations
                license_amount = round(total * TRADITIONAL_LICENSE_SPLIT, 2)
                support_amount = round(total - license_amount, 2)  # remainder to avoid rounding issues

                obligations.append(
                    PerformanceObligation(
                        id=f"PO-{po_counter:03d}",
                        description=f"Coder Premium — License ({combined_desc})",
                        product_type=ProductType.LICENSE.value,
                        is_distinct=True,
                        recognition_pattern=RecognitionPattern.POINT_IN_TIME.value,
                        asc_reference="ASC 606-10-25-14 through 25-22; ASC 606-10-55-54",
                        rationale=(
                            "Coder Premium includes a software license component that grants "
                            "a right to use intellectual property as it exists at a point in time. "
                            "The license is capable of being distinct and is separately identifiable. "
                            "Allocated 20% of the Coder Premium line item total based on "
                            "established SSP evidence (historical 20/80 split)."
                        ),
                        line_item_total=license_amount,
                    )
                )
                po_counter += 1
                obligations.append(
                    PerformanceObligation(
                        id=f"PO-{po_counter:03d}",
                        description=f"Coder Premium — Support & Maintenance ({combined_desc})",
                        product_type=ProductType.SUPPORT.value,
                        is_distinct=True,
                        recognition_pattern=RecognitionPattern.RATABLE.value,
                        asc_reference="ASC 606-10-25-14 through 25-22; ASC 606-10-55-18",
                        rationale=(
                            "Coder Premium includes a support and maintenance component — "
                            "a stand-ready obligation to provide updates, bug fixes, and technical "
                            "support over the contract term. The customer simultaneously receives "
                            "and consumes the benefits (ASC 606-10-25-27a). "
                            "Allocated 80% of the Coder Premium line item total based on "
                            "established SSP evidence (historical 20/80 split)."
                        ),
                        line_item_total=support_amount,
                    )
                )

        return obligations

    # ------------------------------------------------------------------
    # Step 4 — Allocate Transaction Price (Relative SSP)
    # ------------------------------------------------------------------
    def allocate_ssp(
        self, order: OrderForm, obligations: list[PerformanceObligation]
    ) -> list[SSPAllocation]:
        """
        ASC 606-10-32-28 through 32-41: Allocate the transaction price
        to each performance obligation on a relative standalone selling
        price (SSP) basis.
        """
        tcv = order.total_contract_value
        allocations: list[SSPAllocation] = []

        # Determine raw SSP for each obligation
        raw_ssps: list[tuple[PerformanceObligation, float, str, list[str]]] = []

        for po in obligations:
            warnings: list[str] = []

            if po.product_type == ProductType.AWB.value:
                # AWB: usage-based — SSP is the contractual rate
                ssp = po.line_item_total
                approach = SSPEstimationApproach.CONTRACTUAL_RATE.value
                warnings.append(
                    "AWB uses contractual rate as SSP (variable consideration). "
                    "Ensure the variable consideration constraint per "
                    "ASC 606-10-32-11 is evaluated each reporting period."
                )

            elif po.product_type == ProductType.AI_GOVERNANCE.value:
                # New product — no historical SSP
                ssp = po.line_item_total  # start with contractual price as placeholder
                approach = SSPEstimationApproach.ADJUSTED_MARKET_ASSESSMENT.value
                warnings.extend([
                    "AI Governance is a NEW product — no historical SSP exists.",
                    "Management must select an estimation approach per ASC 606-10-32-33:",
                    "  (a) Adjusted market assessment approach — evaluate the market "
                    "and estimate the price customers would pay (RECOMMENDED as primary).",
                    "  (b) Expected cost plus margin approach — forecast costs and add "
                    "an appropriate margin.",
                    "  (c) Residual approach (ASC 606-10-32-34) — ONLY permitted if the "
                    "SSP is highly variable or uncertain. Must meet criteria in "
                    "ASC 606-10-32-34(a) or (b).",
                    "The allocated amount below uses the contractual price as a starting "
                    "point; this MUST be validated against the selected estimation approach.",
                ])

            elif po.product_type in (ProductType.LICENSE.value, ProductType.SUPPORT.value):
                # Check if this PO came from Coder Premium decomposition
                is_from_coder_premium = "Coder Premium" in po.description

                if is_from_coder_premium:
                    # Already split 20/80 during PO identification — use as-is
                    ssp = po.line_item_total
                    approach = SSPEstimationApproach.HISTORICAL.value
                    warnings.append(
                        "Coder Premium bundled product: SSP derived from established "
                        "20% license / 80% support split applied during performance "
                        "obligation identification."
                    )
                elif order.is_traditional_deal and not order.has_awb:
                    # Traditional deal with separate license/support line items
                    trad_total = sum(
                        o.line_item_total
                        for o in obligations
                        if o.product_type
                        in (ProductType.LICENSE.value, ProductType.SUPPORT.value)
                    )
                    if po.product_type == ProductType.LICENSE.value:
                        ssp = round(trad_total * TRADITIONAL_LICENSE_SPLIT, 2)
                    else:
                        ssp = round(trad_total * TRADITIONAL_SUPPORT_SPLIT, 2)
                    approach = SSPEstimationApproach.HISTORICAL.value
                    warnings.append(
                        "Using historical SSP split: 20% license / 80% support "
                        "for traditional deals (order date on or before 12/31/2025)."
                    )
                else:
                    # Non-traditional or mixed deal — use contractual price as SSP
                    ssp = po.line_item_total
                    approach = SSPEstimationApproach.HISTORICAL.value
                    if not order.is_traditional_deal:
                        warnings.append(
                            "Post-2025 deal: Historical 20/80 split may not apply. "
                            "SSP set to contractual price — validate against current "
                            "SSP evidence."
                        )

            raw_ssps.append((po, ssp, approach, warnings))

        # Relative SSP allocation per ASC 606-10-32-31
        total_ssp = sum(ssp for _, ssp, _, _ in raw_ssps)
        if total_ssp == 0:
            total_ssp = 1.0  # avoid division by zero

        # Allocate TCV proportionally, with rounding reconciliation
        allocated_total = 0.0
        for i, (po, ssp, approach, warnings) in enumerate(raw_ssps):
            pct = ssp / total_ssp
            allocated = round(tcv * pct, 2)
            allocated_total += allocated

            allocations.append(
                SSPAllocation(
                    obligation_id=po.id,
                    description=po.description,
                    product_type=po.product_type,
                    standalone_selling_price=round(ssp, 2),
                    ssp_estimation_approach=approach,
                    allocated_amount=allocated,
                    allocation_percentage=pct,
                    asc_reference="ASC 606-10-32-28 through 32-35 (relative SSP method)",
                    warnings=warnings,
                )
            )

        # Reconcile rounding difference onto the largest allocation
        rounding_diff = round(tcv - allocated_total, 2)
        if rounding_diff != 0.0 and allocations:
            largest = max(allocations, key=lambda a: a.allocated_amount)
            largest.allocated_amount = round(largest.allocated_amount + rounding_diff, 2)

        return allocations

    # ------------------------------------------------------------------
    # Step 5 — Determine Recognition Timing
    # ------------------------------------------------------------------
    def determine_recognition_timing(
        self,
        order: OrderForm,
        obligations: list[PerformanceObligation],
        allocations: list[SSPAllocation],
    ) -> list[RecognitionSchedule]:
        """
        ASC 606-10-25-23 through 25-30: Determine when (or as) each
        performance obligation is satisfied and revenue is recognized.
        """
        alloc_map = {a.obligation_id: a for a in allocations}
        schedules: list[RecognitionSchedule] = []

        start = order.contract_start_parsed
        end = order.contract_end_parsed
        months = _month_range(start, end)
        num_months = len(months)

        for po in obligations:
            alloc = alloc_map.get(po.id)
            if alloc is None:
                continue
            amount = alloc.allocated_amount

            if po.product_type == ProductType.LICENSE.value:
                # Point-in-time — full amount recognized in the first month
                monthly = [{"month": months[0], "amount": round(amount, 2)}]
                for m in months[1:]:
                    monthly.append({"month": m, "amount": 0.0})
                schedules.append(
                    RecognitionSchedule(
                        obligation_id=po.id,
                        description=po.description,
                        product_type=po.product_type,
                        recognition_pattern=RecognitionPattern.POINT_IN_TIME.value,
                        allocated_amount=amount,
                        recognition_start=start.isoformat(),
                        recognition_end=start.isoformat(),
                        monthly_schedule=monthly,
                        asc_reference=(
                            "ASC 606-10-25-30 (point in time); "
                            "ASC 606-10-55-54 (right-to-use license)"
                        ),
                        notes=(
                            "Software license recognized at point in time upon "
                            "delivery/go-live when the customer obtains control "
                            "of the software."
                        ),
                    )
                )

            elif po.product_type == ProductType.SUPPORT.value:
                # Ratable — straight-line over contract term
                monthly_amount = round(amount / num_months, 2)
                running = 0.0
                monthly: list[dict] = []
                for i, m in enumerate(months):
                    if i == len(months) - 1:
                        # put remainder in last month to reconcile rounding
                        month_amt = round(amount - running, 2)
                    else:
                        month_amt = monthly_amount
                    running += month_amt
                    monthly.append({"month": m, "amount": round(month_amt, 2)})

                schedules.append(
                    RecognitionSchedule(
                        obligation_id=po.id,
                        description=po.description,
                        product_type=po.product_type,
                        recognition_pattern=RecognitionPattern.RATABLE.value,
                        allocated_amount=amount,
                        recognition_start=start.isoformat(),
                        recognition_end=end.isoformat(),
                        monthly_schedule=monthly,
                        asc_reference=(
                            "ASC 606-10-25-27(a) (over time — simultaneous "
                            "receipt and consumption); ASC 606-10-55-18"
                        ),
                        notes=(
                            "Support & maintenance recognized ratably (straight-line) "
                            "over the contract term as the customer simultaneously "
                            "receives and consumes the benefits."
                        ),
                    )
                )

            elif po.product_type == ProductType.AWB.value:
                # Usage-based — evenly estimated for illustration, flagged as variable
                estimated_monthly = round(amount / num_months, 2)
                running = 0.0
                monthly: list[dict] = []
                for i, m in enumerate(months):
                    if i == len(months) - 1:
                        month_amt = round(amount - running, 2)
                    else:
                        month_amt = estimated_monthly
                    running += month_amt
                    monthly.append({"month": m, "amount": round(month_amt, 2)})

                schedules.append(
                    RecognitionSchedule(
                        obligation_id=po.id,
                        description=po.description,
                        product_type=po.product_type,
                        recognition_pattern=RecognitionPattern.USAGE_BASED.value,
                        allocated_amount=amount,
                        recognition_start=start.isoformat(),
                        recognition_end=end.isoformat(),
                        monthly_schedule=monthly,
                        asc_reference=(
                            "ASC 606-10-32-40 (variable consideration); "
                            "ASC 606-10-32-11 (constraint on variable consideration); "
                            "ASC 606-10-55-65 (sales/usage-based royalty exception)"
                        ),
                        notes=(
                            "AWB revenue is recognized as usage occurs. The monthly "
                            "schedule shown is an ESTIMATE based on even distribution; "
                            "actual recognition depends on metered consumption. "
                            "Variable consideration constraint must be reassessed each "
                            "reporting period — include only amounts for which it is "
                            "probable that a significant reversal will not occur."
                        ),
                    )
                )

            elif po.product_type == ProductType.AI_GOVERNANCE.value:
                # Default: point-in-time (perpetual add-on assumption)
                # but flag that term-based would require ratable
                monthly = [{"month": months[0], "amount": round(amount, 2)}]
                for m in months[1:]:
                    monthly.append({"month": m, "amount": 0.0})

                schedules.append(
                    RecognitionSchedule(
                        obligation_id=po.id,
                        description=po.description,
                        product_type=po.product_type,
                        recognition_pattern=RecognitionPattern.POINT_IN_TIME.value,
                        allocated_amount=amount,
                        recognition_start=start.isoformat(),
                        recognition_end=start.isoformat(),
                        monthly_schedule=monthly,
                        asc_reference=(
                            "ASC 606-10-25-30 (point in time); "
                            "ASC 606-10-55-54 (functional IP — right to use)"
                        ),
                        notes=(
                            "AI Governance License Add-on — REQUIRES JUDGMENT. "
                            "If the license is perpetual (right-to-use), recognize "
                            "at point in time upon delivery. If the license is "
                            "term-based (right-to-access / symbolic IP), recognize "
                            "ratably over the license term per ASC 606-10-55-58. "
                            "Current schedule assumes perpetual/point-in-time — "
                            "VALIDATE license type with legal/contracts team."
                        ),
                    )
                )

        return schedules

    # ------------------------------------------------------------------
    # Generate Full ASC 606 Checklist
    # ------------------------------------------------------------------
    def generate_checklist(
        self,
        order: OrderForm,
        obligations: list[PerformanceObligation],
        allocations: list[SSPAllocation],
        schedules: list[RecognitionSchedule],
    ) -> dict:
        """Build the structured five-step checklist with flags and schedules."""

        warnings: list[str] = []
        flags: list[dict] = []

        # --- Step 1: Identify the contract ---
        step1_criteria = [
            {
                "criterion": "Parties have approved the contract (ASC 606-10-25-1a)",
                "status": "pass" if order.customer_name else "needs_review",
                "detail": f"Customer: {order.customer_name}; Order date: {order.order_date}",
            },
            {
                "criterion": "Rights of each party are identifiable (ASC 606-10-25-1b)",
                "status": "pass",
                "detail": (
                    f"{len(order.line_items)} line item(s) define goods/services "
                    "to be transferred."
                ),
            },
            {
                "criterion": "Payment terms are identifiable (ASC 606-10-25-1c)",
                "status": "pass" if order.payment_terms else "needs_review",
                "detail": order.payment_terms or "Payment terms not specified — review contract.",
            },
            {
                "criterion": "Contract has commercial substance (ASC 606-10-25-1d)",
                "status": "pass",
                "detail": (
                    f"Total contract value: ${order.total_contract_value:,.2f}. "
                    "Risk, timing, or amount of future cash flows expected to change."
                ),
            },
            {
                "criterion": "Collection is probable (ASC 606-10-25-1e)",
                "status": "needs_review",
                "detail": (
                    "Assess customer's ability and intention to pay. Review credit "
                    "history and financial standing of the customer."
                ),
            },
        ]

        # --- Step 2: Identify performance obligations ---
        step2_obligations = [po.to_dict() for po in obligations]

        # --- Step 3: Determine transaction price ---
        fixed_consideration = sum(
            li.total
            for li in order.line_items
            if li.product_type not in (ProductType.AWB.value,)
        )
        variable_consideration = sum(
            li.total
            for li in order.line_items
            if li.product_type == ProductType.AWB.value
        )

        step3 = {
            "total_contract_value": round(order.total_contract_value, 2),
            "fixed_consideration": round(fixed_consideration, 2),
            "variable_consideration": round(variable_consideration, 2),
            "has_variable_consideration": variable_consideration > 0,
            "variable_consideration_details": [],
            "significant_financing_component": {
                "present": False,
                "detail": (
                    "Evaluate whether the timing of payments differs significantly "
                    "from the timing of transfer. If the contract term is one year "
                    "or less, the practical expedient in ASC 606-10-32-18 may apply."
                ),
            },
            "asc_references": [
                "ASC 606-10-32-2 through 32-27 (transaction price)",
                "ASC 606-10-32-5 through 32-10 (variable consideration)",
                "ASC 606-10-32-11 through 32-13 (constraint on variable consideration)",
            ],
        }

        if variable_consideration > 0:
            step3["variable_consideration_details"].append({
                "component": "AWB usage-based fees",
                "estimated_amount": round(variable_consideration, 2),
                "estimation_method": "Expected value or most likely amount",
                "constraint_assessment": (
                    "Include in the transaction price only to the extent that it is "
                    "probable that a significant reversal in cumulative revenue will "
                    "not occur when the uncertainty is subsequently resolved "
                    "(ASC 606-10-32-11)."
                ),
            })

        # --- Step 4: Allocate transaction price ---
        step4_allocations = [a.to_dict() for a in allocations]

        # --- Step 5: Recognize revenue ---
        step5_schedules = [s.to_dict() for s in schedules]

        # Build combined monthly schedule
        all_months_set: set[str] = set()
        for s in schedules:
            for entry in s.monthly_schedule:
                all_months_set.add(entry["month"])
        all_months = sorted(all_months_set)

        combined_monthly: list[dict] = []
        for m in all_months:
            row: dict = {"month": m}
            total_month = 0.0
            for s in schedules:
                amt = 0.0
                for entry in s.monthly_schedule:
                    if entry["month"] == m:
                        amt = entry["amount"]
                        break
                row[s.obligation_id] = round(amt, 2)
                total_month += amt
            row["total"] = round(total_month, 2)
            combined_monthly.append(row)

        # --- Flags & warnings ---
        if order.has_ai_governance:
            flags.append({
                "severity": "high",
                "category": "SSP Estimation",
                "message": (
                    "AI Governance License Add-on is a NEW product with no historical "
                    "SSP. Management must determine and document the estimation approach "
                    "per ASC 606-10-32-33. See Step 4 warnings for details."
                ),
                "asc_reference": "ASC 606-10-32-33 through 32-35",
                "action_required": True,
            })
            flags.append({
                "severity": "medium",
                "category": "Recognition Timing",
                "message": (
                    "AI Governance License: determine whether the license is a "
                    "right-to-use (functional IP → point-in-time) or right-to-access "
                    "(symbolic IP → over time). This impacts revenue timing."
                ),
                "asc_reference": "ASC 606-10-55-54 through 55-60",
                "action_required": True,
            })

        if order.has_awb:
            flags.append({
                "severity": "medium",
                "category": "Variable Consideration",
                "message": (
                    "AWB includes variable consideration tied to usage. The constraint "
                    "must be reassessed each reporting period. Actual revenue depends "
                    "on metered consumption data."
                ),
                "asc_reference": "ASC 606-10-32-11 through 32-13; ASC 606-10-32-40",
                "action_required": True,
            })

        if order.is_traditional_deal and not order.has_awb and not order.has_coder_premium:
            flags.append({
                "severity": "low",
                "category": "SSP Method",
                "message": (
                    "Traditional deal: using historical 20% license / 80% support SSP "
                    "split. Ensure this remains supported by current SSP evidence."
                ),
                "asc_reference": "ASC 606-10-32-33",
                "action_required": False,
            })

        if order.has_coder_premium:
            flags.append({
                "severity": "low",
                "category": "Bundled Product Decomposition",
                "message": (
                    "Coder Premium line item(s) automatically decomposed into separate "
                    "License (20%) and Support (80%) performance obligations based on "
                    "established SSP evidence."
                ),
                "asc_reference": "ASC 606-10-32-33 (SSP estimation — historical evidence)",
                "action_required": False,
            })

        # Check for collectibility
        flags.append({
            "severity": "medium",
            "category": "Collectibility",
            "message": (
                "Step 1 criterion (e): Confirm that it is probable the entity will "
                "collect substantially all of the consideration to which it is entitled."
            ),
            "asc_reference": "ASC 606-10-25-1(e)",
            "action_required": True,
        })

        # Aggregate warnings from allocations
        for a in allocations:
            for w in a.warnings:
                if w not in warnings:
                    warnings.append(w)

        # Aggregate notes from schedules
        for s in schedules:
            if s.notes and s.notes not in warnings:
                warnings.append(s.notes)

        return {
            "summary": {
                "customer_name": order.customer_name,
                "order_date": order.order_date,
                "contract_period": f"{order.contract_start} to {order.contract_end}",
                "contract_months": order.contract_months,
                "total_contract_value": round(order.total_contract_value, 2),
                "num_performance_obligations": len(obligations),
                "deal_type": (
                    "traditional"
                    if (order.is_traditional_deal and not order.has_awb)
                    else "modern/mixed"
                ),
                "has_awb": order.has_awb,
                "has_ai_governance": order.has_ai_governance,
                "has_coder_premium": order.has_coder_premium,
                "payment_terms": order.payment_terms,
                "renewal_terms": order.renewal_terms,
            },
            "five_step_analysis": {
                "step_1_identify_contract": {
                    "title": "Step 1: Identify the Contract with a Customer",
                    "asc_reference": "ASC 606-10-25-1",
                    "criteria": step1_criteria,
                },
                "step_2_identify_obligations": {
                    "title": "Step 2: Identify the Performance Obligations",
                    "asc_reference": "ASC 606-10-25-14 through 25-22",
                    "performance_obligations": step2_obligations,
                },
                "step_3_transaction_price": {
                    "title": "Step 3: Determine the Transaction Price",
                    "asc_reference": "ASC 606-10-32-2 through 32-27",
                    **step3,
                },
                "step_4_allocate_price": {
                    "title": "Step 4: Allocate the Transaction Price",
                    "asc_reference": "ASC 606-10-32-28 through 32-41",
                    "method": "Relative standalone selling price (SSP) method",
                    "allocations": step4_allocations,
                },
                "step_5_recognize_revenue": {
                    "title": "Step 5: Recognize Revenue",
                    "asc_reference": "ASC 606-10-25-23 through 25-30",
                    "schedules": step5_schedules,
                },
            },
            "monthly_revenue_schedule": combined_monthly,
            "flags": flags,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Top-level entry point
    # ------------------------------------------------------------------
    def analyze(self, order: OrderForm) -> dict:
        """Run the full five-step ASC 606 analysis and return a checklist dict."""
        obligations = self.identify_performance_obligations(order)
        allocations = self.allocate_ssp(order, obligations)
        schedules = self.determine_recognition_timing(order, obligations, allocations)
        checklist = self.generate_checklist(order, obligations, allocations, schedules)
        return checklist
