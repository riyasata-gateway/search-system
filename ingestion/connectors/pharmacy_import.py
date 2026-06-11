import io
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd

from core.logging import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS = {"cnk", "quantity", "sale_date"}
OPTIONAL_COLUMNS = {"product_name", "revenue", "ean"}


def parse_pharmacy_file(content: str, filename: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse CSV or XLSX pharmacy sales/inventory upload.
    Returns (records, errors).

    Expected columns: cnk, quantity, sale_date
    Optional columns: product_name, revenue, ean
    """
    errors: List[str] = []
    records: List[Dict[str, Any]] = []

    try:
        if filename.endswith(".xlsx"):
            df = pd.read_excel(io.StringIO(content))
        else:
            df = pd.read_csv(io.StringIO(content))
    except Exception as exc:
        return [], [f"Failed to parse file: {exc}"]

    df.columns = [c.strip().lower() for c in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        return [], [f"Missing required columns: {missing}"]

    for idx, row in df.iterrows():
        row_errors = []

        cnk = str(row.get("cnk", "")).strip()
        if not cnk:
            row_errors.append(f"Row {idx + 2}: cnk is empty")

        try:
            quantity = int(row["quantity"])
            if quantity < 0:
                row_errors.append(f"Row {idx + 2}: quantity must be non-negative")
        except (ValueError, TypeError):
            row_errors.append(f"Row {idx + 2}: quantity must be a number")
            quantity = 0

        try:
            sale_date = pd.to_datetime(row["sale_date"]).date()
        except Exception:
            row_errors.append(f"Row {idx + 2}: sale_date format not recognised (use YYYY-MM-DD)")
            sale_date = None

        revenue = None
        if "revenue" in row and pd.notna(row["revenue"]):
            try:
                revenue = float(row["revenue"])
            except (ValueError, TypeError):
                row_errors.append(f"Row {idx + 2}: revenue must be a number")

        if row_errors:
            errors.extend(row_errors)
            continue

        records.append({
            "cnk": cnk,
            "quantity": quantity,
            "sale_date": sale_date,
            "revenue": revenue,
            "product_name": str(row.get("product_name", "")).strip() or None,
            "ean": str(row.get("ean", "")).strip() or None,
        })

    logger.info("pharmacy_import_parsed", total_rows=len(df), valid=len(records), errors=len(errors))
    return records, errors
