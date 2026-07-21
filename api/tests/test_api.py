"""API integration tests. Run against a real warehouse database (the same
WAREHOUSE_DB_* / METADATA_DB_* env vars the app itself reads -- see
.env.example) -- these are not mocked, because the whole point of this test
suite is to catch the kind of real, live-only bugs this project's own
development surfaced (e.g. a Pydantic model rejecting a value the database
actually returns). Requires the dbt project to have been run at least once
against the target database (`make dbt-run` or the CI workflow's dbt step).

Run: pytest api/tests/test_api.py -v
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


class TestHealth:
    def test_health_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "warehouse_reachable" in body


class TestProducts:
    def test_list_products_default_pagination(self):
        resp = client.get("/products")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body and "total_items" in body and "page" in body
        assert body["page"] == 1
        assert len(body["items"]) <= body["page_size"]

    def test_list_products_page_size_validation(self):
        resp = client.get("/products?page_size=0")
        assert resp.status_code == 422  # page_size must be >= 1

    def test_list_products_page_size_upper_bound(self):
        resp = client.get("/products?page_size=10000")
        assert resp.status_code == 422  # page_size must be <= 200

    def test_product_fields_are_correctly_typed(self):
        """Regression test: `upc` was briefly returned as an int by the
        warehouse (a CSV/pandas round-trip inferred it as bigint), which a
        naive client would silently mis-handle (leading zeros, no
        arithmetic should ever apply to a UPC). The API's Pydantic model
        enforces str, so this would 500 if the warehouse ever regresses.
        """
        resp = client.get("/products?page_size=1")
        assert resp.status_code == 200
        items = resp.json()["items"]
        if items:
            assert isinstance(items[0]["upc"], (str, type(None)))

    def test_product_performance_not_found(self):
        resp = client.get("/products/DOES-NOT-EXIST/performance")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_product_performance_found(self):
        products = client.get("/products?page_size=1").json()["items"]
        if not products:
            pytest.skip("no products loaded in target database")
        product_id = products[0]["product_id"]
        resp = client.get(f"/products/{product_id}/performance")
        assert resp.status_code == 200
        assert resp.json()["product_id"] == product_id


class TestSales:
    def test_sales_summary_default_group_by_retailer(self):
        resp = client.get("/sales/summary")
        assert resp.status_code == 200
        rows = resp.json()
        assert isinstance(rows, list)
        if rows:
            assert set(["group_key", "units_sold", "net_sales"]).issubset(rows[0].keys())

    def test_sales_summary_group_by_category(self):
        resp = client.get("/sales/summary?group_by=category")
        assert resp.status_code == 200

    def test_sales_summary_invalid_group_by_rejected(self):
        resp = client.get("/sales/summary?group_by=not_a_real_dimension")
        assert resp.status_code == 422

    def test_sales_summary_start_after_end_rejected(self):
        resp = client.get("/sales/summary?start_date=2025-12-31&end_date=2025-01-01")
        assert resp.status_code == 422

    def test_omnichannel_performance_default(self):
        resp = client.get("/sales/omnichannel")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_omnichannel_performance_start_after_end_rejected(self):
        resp = client.get("/sales/omnichannel?start_date=2025-12-31&end_date=2025-01-01")
        assert resp.status_code == 422


class TestInventory:
    def test_stockout_risk_default(self):
        resp = client.get("/inventory/stockout-risk")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_stockout_risk_invalid_level_rejected(self):
        resp = client.get("/inventory/stockout-risk?risk_level=NOT_A_LEVEL")
        assert resp.status_code == 422

    def test_stockout_risk_filtered_items_match_filter(self):
        resp = client.get("/inventory/stockout-risk?risk_level=HIGH&page_size=50")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["stockout_risk_level"] == "HIGH"

    def test_excess_risk_default(self):
        resp = client.get("/inventory/excess-risk")
        assert resp.status_code == 200
        assert "items" in resp.json()


class TestPromotions:
    def test_promotion_performance_default(self):
        resp = client.get("/promotions/performance")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_promotion_performance_min_lift_filter(self):
        resp = client.get("/promotions/performance?min_lift_percentage=0")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            if item["lift_percentage"] is not None:
                assert item["lift_percentage"] >= 0


class TestShipments:
    def test_reconciliation_default(self):
        resp = client.get("/shipments/reconciliation")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_reconciliation_signal_filter(self):
        resp = client.get("/shipments/reconciliation?signal=ALIGNED&page_size=50")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["reconciliation_signal"] == "ALIGNED"


class TestRetailers:
    def test_retailer_performance_not_found(self):
        resp = client.get("/retailers/NOPE/performance")
        assert resp.status_code == 404

    def test_retailer_performance_found(self):
        resp = client.get("/retailers/RTL-WMT/performance")
        if resp.status_code == 404:
            pytest.skip("RTL-WMT not present in target database")
        assert resp.status_code == 200
        assert resp.json()["retailer_id"] == "RTL-WMT"


class TestDataQualityAndOps:
    def test_data_quality_latest_returns_list(self):
        resp = client.get("/data-quality/latest")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_pipeline_runs_default(self):
        resp = client.get("/pipeline-runs")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_pipeline_runs_status_filter_validation(self):
        resp = client.get("/pipeline-runs?status=NOT_A_STATUS")
        assert resp.status_code == 422


class TestOpenAPIDocs:
    def test_openapi_schema_available(self):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["title"] == "CPG Pulse API"

    def test_docs_ui_available(self):
        resp = client.get("/docs")
        assert resp.status_code == 200
