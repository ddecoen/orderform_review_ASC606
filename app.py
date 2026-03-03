"""
ASC 606 Revenue Recognition Analysis Tool — Flask Application
==============================================================
Routes:
  GET  /             — Serves the frontend SPA
  POST /api/upload   — Accepts a PDF, extracts text, runs ASC 606 analysis
  POST /api/analyze  — Accepts manual JSON deal terms, runs ASC 606 analysis
"""

from __future__ import annotations

import os
import tempfile
import traceback
from datetime import date

from flask import Flask, jsonify, request, render_template, send_from_directory

from engine import ASC606Analyzer, LineItem, OrderForm
from pdf_parser import parse_pdf_to_order

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit

ALLOWED_EXTENSIONS = {"pdf"}
analyzer = ASC606Analyzer()


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the frontend."""
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_pdf():
    """
    Accept a PDF file upload, extract text, parse order form data,
    and run the full ASC 606 analysis.

    Returns JSON:
      - parse_result: metadata about the PDF parsing
      - analysis: full five-step checklist (if parsing succeeded)
      - raw_text: extracted text (always)
      - needs_manual_entry: bool flag
    """
    try:
        if "file" not in request.files:
            return jsonify({
                "error": "No file provided. Send a PDF as multipart form data with key 'file'.",
                "success": False,
            }), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({
                "error": "Empty filename. Please select a PDF file.",
                "success": False,
            }), 400

        if not _allowed_file(file.filename):
            return jsonify({
                "error": f"Invalid file type. Only PDF files are accepted (got: {file.filename}).",
                "success": False,
            }), 400

        # Save to a temp file for pdfplumber
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
            file.save(tmp_path)

        try:
            result = parse_pdf_to_order(tmp_path)
        finally:
            os.unlink(tmp_path)  # clean up temp file

        response: dict = {
            "success": result["success"],
            "raw_text": result["raw_text"],
            "parse_warnings": result["parse_warnings"],
            "needs_manual_entry": result["needs_manual_entry"],
        }

        if result["order"] is not None and result["order"].line_items:
            order: OrderForm = result["order"]
            analysis = analyzer.analyze(order)
            response["analysis"] = analysis
            response["parsed_order"] = {
                "customer_name": order.customer_name,
                "order_date": order.order_date,
                "contract_start": order.contract_start,
                "contract_end": order.contract_end,
                "total_contract_value": order.total_contract_value,
                "line_items": [
                    {
                        "description": li.description,
                        "quantity": li.quantity,
                        "unit_price": li.unit_price,
                        "total": li.total,
                        "product_type": li.product_type,
                    }
                    for li in order.line_items
                ],
                "payment_terms": order.payment_terms,
                "renewal_terms": order.renewal_terms,
            }
        else:
            response["analysis"] = None
            response["parsed_order"] = None
            if not result["parse_warnings"]:
                response["parse_warnings"] = [
                    "Could not extract sufficient data from the PDF. "
                    "Please use manual entry via /api/analyze."
                ]

        return jsonify(response), 200

    except Exception as exc:
        return jsonify({
            "error": f"Server error processing upload: {str(exc)}",
            "traceback": traceback.format_exc(),
            "success": False,
        }), 500


@app.route("/api/analyze", methods=["POST"])
def analyze_manual():
    """
    Accept manual JSON input of deal terms and run ASC 606 analysis.

    Expected JSON body:
    {
        "customer_name": "Acme Corp",
        "order_date": "2025-06-01",
        "contract_start": "2025-07-01",
        "contract_end": "2026-06-30",
        "total_contract_value": 500000.00,
        "line_items": [
            {
                "description": "Enterprise Software License",
                "quantity": 1,
                "unit_price": 100000.00,
                "total": 100000.00,
                "product_type": "license"
            },
            ...
        ],
        "payment_terms": "Net 30",
        "renewal_terms": "Auto-renew annually"
    }
    """
    try:
        data = request.get_json(force=True, silent=True)
        if data is None:
            return jsonify({
                "error": "Invalid or missing JSON body.",
                "success": False,
                "expected_format": {
                    "customer_name": "string",
                    "order_date": "YYYY-MM-DD",
                    "contract_start": "YYYY-MM-DD",
                    "contract_end": "YYYY-MM-DD",
                    "total_contract_value": 0.0,
                    "line_items": [
                        {
                            "description": "string",
                            "quantity": 1,
                            "unit_price": 0.0,
                            "total": 0.0,
                            "product_type": "license|support|awb|ai_governance",
                        }
                    ],
                    "payment_terms": "string (optional)",
                    "renewal_terms": "string (optional)",
                },
            }), 400

        # Validate required fields
        required = [
            "customer_name",
            "order_date",
            "contract_start",
            "contract_end",
            "total_contract_value",
            "line_items",
        ]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({
                "error": f"Missing required fields: {missing}",
                "success": False,
            }), 400

        if not isinstance(data["line_items"], list) or len(data["line_items"]) == 0:
            return jsonify({
                "error": "line_items must be a non-empty list.",
                "success": False,
            }), 400

        # Validate each line item
        li_required = ["description", "quantity", "unit_price", "total", "product_type"]
        for i, li in enumerate(data["line_items"]):
            li_missing = [f for f in li_required if f not in li]
            if li_missing:
                return jsonify({
                    "error": f"Line item {i} is missing fields: {li_missing}",
                    "success": False,
                }), 400

        # Build the OrderForm
        try:
            line_items = [
                LineItem(
                    description=li["description"],
                    quantity=li["quantity"],
                    unit_price=li["unit_price"],
                    total=li["total"],
                    product_type=li["product_type"],
                )
                for li in data["line_items"]
            ]
        except ValueError as ve:
            return jsonify({
                "error": f"Invalid line item data: {str(ve)}",
                "success": False,
            }), 400

        try:
            order = OrderForm(
                customer_name=data["customer_name"],
                order_date=data["order_date"],
                contract_start=data["contract_start"],
                contract_end=data["contract_end"],
                total_contract_value=data["total_contract_value"],
                line_items=line_items,
                payment_terms=data.get("payment_terms", ""),
                renewal_terms=data.get("renewal_terms", ""),
            )
        except ValueError as ve:
            return jsonify({
                "error": f"Invalid order data: {str(ve)}",
                "success": False,
            }), 400

        # Run analysis
        analysis = analyzer.analyze(order)

        return jsonify({
            "success": True,
            "analysis": analysis,
        }), 200

    except Exception as exc:
        return jsonify({
            "error": f"Server error during analysis: {str(exc)}",
            "traceback": traceback.format_exc(),
            "success": False,
        }), 500


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "asc606-analyzer"}), 200


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)

    # Create a minimal placeholder index.html if it doesn't exist
    index_path = os.path.join("static", "index.html")
    if not os.path.exists(index_path):
        with open(index_path, "w") as f:
            f.write(
                "<!DOCTYPE html><html><head><title>ASC 606 Analyzer</title></head>"
                "<body><h1>ASC 606 Revenue Recognition Analyzer</h1>"
                "<p>Use <code>POST /api/upload</code> (PDF) or "
                "<code>POST /api/analyze</code> (JSON) to run analysis.</p>"
                "</body></html>"
            )

    app.run(host="0.0.0.0", port=5000, debug=True)
