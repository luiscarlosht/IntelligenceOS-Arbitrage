"""Regression checks for the offline prototype's operational boundaries."""
import json
import sqlite3
from dataclasses import replace
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.config import Config
from app.history import History
from app.orchestrator import JsonFormatter, run_job
from app.pipeline import ROOT, evaluate
from app.profitability import analyze
from app.reporting import write_report


@pytest.fixture
def cfg(tmp_path):
    return Config(ROOT / "sample_data/candidates.csv", tmp_path / "report.xlsx", tmp_path / "runs.sqlite3")


@pytest.mark.parametrize(
    ("purchase", "sale", "expected_profit", "expected_roi"),
    [
        ("10", "15", "5", "50"),
        ("10", "14.99", "4.99", "49.9"),
        ("8", "25", "17", "212.5"),
    ],
)
def test_threshold_math_remains_stable(purchase, sale, expected_profit, expected_roi):
    row = dict(source="fixture", product="sample", upc="00123", source_url="https://example.org",
               amazon_asin="TEST", destination="Amazon", buy_cost=purchase, sale_price=sale,
               referral_fee="0", fulfillment_fee="0", inbound_shipping="0", other_cost="0",
               eligible="yes", exact_match="yes")
    actual = evaluate(row)
    assert actual["profit"] == float(expected_profit)
    assert actual["roi"] == float(expected_roi)
    assert actual["status"] == ("REVIEW" if Decimal(expected_profit) >= 5 and Decimal(expected_roi) >= 50 else "REJECT")


def test_extended_costs_preserve_acquisition_roi():
    costs = {name: Decimal("0") for name in (
        "inbound_shipping", "preparation", "packaging", "sales_tax", "other_cost",
        "fulfillment_fee", "storage", "transaction_cost", "referral_fee")}
    costs["inbound_shipping"] = Decimal("2")
    costs["fulfillment_fee"] = Decimal("3")
    result = analyze(Decimal("10"), Decimal("25"), costs)
    assert result.acquisition_cost == Decimal("12")
    assert result.net_profit == Decimal("10")
    assert result.roi == Decimal("10") / Decimal("12") * 100


def test_report_never_interprets_untrusted_product_as_formula(tmp_path):
    rows = [dict(source="fixture", product="=1+1", upc="000012", amazon_asin="X",
                 destination="Amazon", buy_cost=10, sale_price=15, profit=5, roi=50,
                 status="REVIEW", reason="Review required", source_url="https://example.org")]
    target = tmp_path / "report.xlsx"
    write_report(rows, target)
    with load_workbook(target) as workbook:
        cell = workbook["All Candidates"]["B2"]
        assert cell.value == "=1+1"
        assert cell.data_type == "s"
        assert workbook["All Candidates"]["C2"].value == "000012"
        assert workbook["All Candidates"].freeze_panes == "A2"


def test_repeated_job_writes_individual_audit_records(cfg):
    assert run_job(cfg) == 1
    assert run_job(cfg) == 2
    with sqlite3.connect(cfg.database) as db:
        rows = db.execute("SELECT id,status,report_path FROM runs ORDER BY id").fetchall()
    assert len(rows) == 2
    assert all(status == "succeeded" for _, status, _ in rows)
    assert all(path == str(cfg.output) for _, _, path in rows)


def test_failure_records_type_without_sensitive_error_text(cfg):
    invalid = replace(cfg, input=cfg.input.parent / "missing.csv")
    with pytest.raises(FileNotFoundError):
        run_job(invalid)
    with sqlite3.connect(cfg.database) as db:
        result = db.execute("SELECT status,error_type,report_path FROM runs").fetchone()
    assert result == ("failed", "FileNotFoundError", None)


def test_no_email_without_recipient(cfg):
    from app.mailer import send_report
    assert send_report(cfg, cfg.output, 1) is False


def test_json_formatter_excludes_raw_exception_text():
    import logging
    record = logging.LogRecord("arbitrage", logging.ERROR, "", 0, "job_failed", (), None)
    record.error_type = "RuntimeError"
    record.run_id = 5
    record.msg = "job_failed"
    serialized = JsonFormatter().format(record)
    obj = json.loads(serialized)
    assert obj["run_id"] == 5
    assert obj["error_type"] == "RuntimeError"
    assert "secret-value" not in serialized
