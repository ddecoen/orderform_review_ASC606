# ASC 606 Revenue Recognition Analyzer

A web application that analyzes order forms for performance obligations, SSP (standalone selling price) allocation, and revenue recognition timing under ASC 606.

## Features

- **PDF Upload** — drag-and-drop order form PDFs with automatic parsing
- **Manual Entry** — structured form for entering deal terms when PDFs fail to parse
- **ASC 606 Five-Step Analysis**:
  1. Identify the contract (with 606-10-25-1 criteria checklist)
  2. Identify performance obligations (license, support, AWB, AI Governance)
  3. Determine transaction price (fixed vs variable consideration)
  4. Allocate transaction price (relative SSP method)
  5. Recognize revenue (point-in-time, ratable, usage-based)
- **Monthly Revenue Schedule** — tabular and chart visualization
- **Flags & Warnings** — severity-ranked items requiring judgment

## Product Types Supported

| Product | Recognition Pattern | SSP Approach |
|---------|-------------------|--------------|
| **License** | Point-in-time | Historical (20% of traditional deals through 12/31/2025) |
| **Support** | Ratable over term | Historical (80% of traditional deals through 12/31/2025) |
| **AWB** (Agent Workspace Builds) | Usage-based | Contractual rate (variable consideration) |
| **AI Governance Add-on** | Point-in-time (requires judgment) | **Flagged for estimation** — no historical SSP |

## Business Rules

### Traditional Deals (order date ≤ 12/31/2025)
- Historical 20/80 split: 20% license, 80% support
- Based on established pricing patterns

### Modern Deals (order date > 12/31/2025)
- Each product uses individual SSP
- AWB: usage-based, contractual rate
- AI Governance: **requires SSP estimation** per ASC 606-10-32-33:
  - Adjusted market assessment (recommended)
  - Expected cost plus margin
  - Residual approach (only if highly variable/uncertain)

### Variable Consideration
- AWB revenue subject to constraint per ASC 606-10-32-11
- Recognized only when it's probable a significant reversal won't occur
- Reassessed each reporting period

## Installation

```bash
pip install -r requirements.txt
```

## Running the Application

```bash
python app.py
```

The server runs on `http://localhost:5000` (or `http://0.0.0.0:5000` for external access).

## API Endpoints

### `POST /api/upload`
Upload a PDF order form for analysis.

**Request:**
```bash
curl -X POST http://localhost:5000/api/upload \
  -F "file=@order_form.pdf"
```

**Response:**
```json
{
  "success": true,
  "needs_manual_entry": false,
  "parse_warnings": [],
  "parsed_order": { ... },
  "analysis": { ... }
}
```

### `POST /api/analyze`
Submit order details as JSON for analysis.

**Request:**
```bash
curl -X POST http://localhost:5000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "customer_name": "TechCo Inc",
    "order_date": "2026-02-01",
    "contract_start": "2026-03-01",
    "contract_end": "2027-02-28",
    "total_contract_value": 750000.00,
    "line_items": [
      {
        "description": "Platform License",
        "quantity": 1,
        "unit_price": 150000,
        "total": 150000,
        "product_type": "license"
      },
      {
        "description": "Support & Maintenance",
        "quantity": 1,
        "unit_price": 350000,
        "total": 350000,
        "product_type": "support"
      },
      {
        "description": "AWB - Agent Workspace Builds",
        "quantity": 100,
        "unit_price": 1000,
        "total": 100000,
        "product_type": "awb"
      },
      {
        "description": "AI Governance Add-on",
        "quantity": 1,
        "unit_price": 150000,
        "total": 150000,
        "product_type": "ai_governance"
      }
    ],
    "payment_terms": "Annual Prepay",
    "renewal_terms": "Auto-Renewal"
  }'
```

**Response:**
```json
{
  "success": true,
  "analysis": {
    "summary": {
      "customer_name": "TechCo Inc",
      "order_date": "2026-02-01",
      "contract_period": "2026-03-01 to 2027-02-28",
      "contract_months": 12,
      "total_contract_value": 750000.0,
      "num_performance_obligations": 4,
      "deal_type": "modern/mixed"
    },
    "five_step_analysis": { ... },
    "monthly_revenue_schedule": [ ... ],
    "flags": [ ... ]
  }
}
```

## File Structure

```
.
├── app.py                  # Flask server (routes + request handling)
├── engine.py               # ASC 606 analysis engine (5-step model)
├── pdf_parser.py           # PDF text extraction + structured parsing
├── requirements.txt        # Python dependencies
└── templates/
    └── index.html          # Frontend (HTML/CSS/JS single-page app)
```

## Key Classes (engine.py)

- **`OrderForm`** — dataclass for deal terms
- **`LineItem`** — dataclass for individual line items
- **`PerformanceObligation`** — identified POs with recognition pattern
- **`SSPAllocation`** — SSP estimation approach + allocated amount
- **`RecognitionSchedule`** — monthly revenue schedule per PO
- **`ASC606Analyzer`** — orchestrates the full 5-step analysis

## Example Use Cases

### Traditional SaaS Deal (Legacy)
- Order date: 2025-06-15
- Products: License + Support
- Result: 20/80 split, $100K license (point-in-time), $400K support (ratable over 12 months)

### Modern Multi-Product Deal
- Order date: 2026-03-01
- Products: License + Support + AWB + AI Governance
- Result: Individual SSP per product, AI Governance flagged for estimation, AWB with variable consideration constraint

## ASC 606 References

The analyzer cites specific sections of the FASB Accounting Standards Codification:
- **ASC 606-10-25-1** — Contract identification criteria
- **ASC 606-10-25-14 through 25-22** — Performance obligations
- **ASC 606-10-32-28 through 32-35** — SSP allocation (relative method)
- **ASC 606-10-32-33** — SSP estimation approaches
- **ASC 606-10-32-40** — Variable consideration (usage-based)
- **ASC 606-10-55-54** — Right-to-use license (point-in-time)
- **ASC 606-10-55-18** — Over-time recognition (stand-ready obligations)

## Warnings & Flags

The analyzer generates severity-ranked flags:
- **High** — AI Governance SSP estimation required (management judgment + documentation)
- **Medium** — Variable consideration constraint reassessment (AWB usage)
- **Medium** — License type determination (right-to-use vs right-to-access)
- **Medium** — Collectibility assessment (Step 1 criterion)

## License

MIT

---

**Built for finance/accounting teams analyzing order forms under ASC 606.**
