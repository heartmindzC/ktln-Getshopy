"""Unit và API tests cho mô hình và endpoint dự đoán mua lại trong 7 ngày tới (Phương án A)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from api.main import app
from api.service import CFModelService, ModelBundle, current_params
from models.cf_recommendation import CollaborativeFiltering
from models.hybrid import build_recommender
from models.next_week import NextWeekPredictor

# Lịch sử đơn hàng nhỏ có chu kỳ rõ ràng:
# - C1 mua P1 đều đặn mỗi 14 ngày (56, 42, 28, 14 ngày trước) -> sắp tới kỳ? Không, hãy để
#   P1 mới mua hôm qua (t_0=1) vs P2 mua đều mỗi 14 ngày với lần cuối cách đây 13 ngày!
# - C1 mua P3 một lần cách đây 200 ngày (đã bỏ lâu).
EVENTS = pd.DataFrame(
    [
        # C1 - P1: vừa mua hôm qua (chu kỳ 14 ngày, t_0 = 1)
        ("C1", "P1", 57, "cat-acc"),
        ("C1", "P1", 43, "cat-acc"),
        ("C1", "P1", 29, "cat-acc"),
        ("C1", "P1", 15, "cat-acc"),
        ("C1", "P1", 1, "cat-acc"),
        # C1 - P2: sát chu kỳ 14 ngày (t_0 = 13)
        ("C1", "P2", 69, "cat-acc"),
        ("C1", "P2", 55, "cat-acc"),
        ("C1", "P2", 41, "cat-acc"),
        ("C1", "P2", 27, "cat-acc"),
        ("C1", "P2", 13, "cat-acc"),
        # C1 - P3: mua 1 lần rất lâu (t_0 = 200)
        ("C1", "P3", 200, "cat-acc"),
        # C2 - P4: mua 2 đơn cùng ngày (Δt = 0)
        ("C2", "P4", 10, "cat-phone"),
        ("C2", "P4", 10, "cat-phone"),
        # C3 - P5: khách mua thưa (1 lần, 5 ngày trước)
        ("C3", "P5", 5, "cat-phone"),
    ],
    columns=["CustomerID", "ProductID", "DaysSince", "ParentCategory"],
)

CF_TRAIN = pd.DataFrame(
    [
        ("C1", "P1", 5, 1),
        ("C1", "P2", 5, 13),
        ("C2", "P4", 2, 10),
        ("C3", "P5", 1, 5),
    ],
    columns=["CustomerID", "ProductID", "Quantity", "DaysSince"],
)

FEATURES = pd.DataFrame(
    [
        ("P1", "cat-acc", "br-a", "lt5", 10),
        ("P2", "cat-acc", "br-a", "lt5", 9),
        ("P3", "cat-acc", "br-a", "lt5", 8),
        ("P4", "cat-phone", "br-b", "gt30", 7),
        ("P5", "cat-phone", "br-b", "15to30", 6),
    ],
    columns=["ProductID", "ParentCategory", "Brand", "PriceBand", "CatalogSold"],
)


class NextWeekPredictorUnitTests(unittest.TestCase):
    def test_probabilities_valid_and_monotone_in_horizon(self) -> None:
        for mtype in ("poisson_gamma", "ipt_hazard"):
            pred = NextWeekPredictor(model_type=mtype).fit(EVENTS)
            p7 = {r["product_id"]: r["purchase_probability"] for r in pred.predict("C1", top_k=10, horizon_days=7, min_prob=0.0)}
            p14 = {r["product_id"]: r["purchase_probability"] for r in pred.predict("C1", top_k=10, horizon_days=14, min_prob=0.0)}
            p30 = {r["product_id"]: r["purchase_probability"] for r in pred.predict("C1", top_k=10, horizon_days=30, min_prob=0.0)}
            self.assertEqual(set(p7), {"P1", "P2", "P3"})
            for pid in p7:
                self.assertGreaterEqual(p7[pid], 0.0)
                self.assertLessEqual(p7[pid], 1.0)
                self.assertLessEqual(p7[pid], p14[pid])
                self.assertLessEqual(p14[pid], p30[pid])

    def test_ipt_hazard_timing_prefers_due_item_over_just_bought_and_churned(self) -> None:
        pred = NextWeekPredictor(model_type="ipt_hazard").fit(EVENTS)
        res = {r["product_id"]: r for r in pred.predict("C1", top_k=10, horizon_days=7, min_prob=0.0)}
        # P2 đang sát chu kỳ 14 ngày (t_0=13) phải cao hơn P1 (vừa mua hôm qua t_0=1)
        self.assertGreater(res["P2"]["purchase_probability"], res["P1"]["purchase_probability"])
        # P2 phải cao hơn hẳn P3 (đã bỏ 200 ngày)
        self.assertGreater(res["P2"]["purchase_probability"], res["P3"]["purchase_probability"])
        self.assertAlmostEqual(res["P2"]["expected_cycle_days"], 14.0, delta=6.0)

    def test_same_day_double_order_no_nan_and_unknown_customer_empty(self) -> None:
        for mtype in ("poisson_gamma", "ipt_hazard"):
            pred = NextWeekPredictor(model_type=mtype).fit(EVENTS)
            res = pred.predict("C2", top_k=5, horizon_days=7, min_prob=0.0)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["purchase_count"], 2)
            self.assertGreaterEqual(res[0]["purchase_probability"], 0.0)
            self.assertLessEqual(res[0]["purchase_probability"], 1.0)
            self.assertEqual(pred.predict("UNKNOWN_CUST"), [])

    def test_reference_mode_max_date_shifts_frozen_days(self) -> None:
        frozen = EVENTS.copy()
        frozen["DaysSince"] = frozen["DaysSince"] + 44  # dữ liệu đóng băng cách hiện tại 44 ngày
        pred_now = NextWeekPredictor(model_type="ipt_hazard", reference_mode="now").fit(frozen)
        pred_shifted = NextWeekPredictor(model_type="ipt_hazard", reference_mode="max_date").fit(frozen)
        self.assertEqual(pred_now.reference_shift_days, 0.0)
        self.assertEqual(pred_shifted.reference_shift_days, 45.0)
        res_shifted = {r["product_id"]: r for r in pred_shifted.predict("C1", min_prob=0.0)}
        self.assertEqual(res_shifted["P1"]["days_since_last_purchase"], 0)
        self.assertEqual(res_shifted["P2"]["days_since_last_purchase"], 12)

    def test_predict_realtime_folds_in_today_purchases(self) -> None:
        pred = NextWeekPredictor(model_type="ipt_hazard").fit(EVENTS)
        before = {r["product_id"]: r for r in pred.predict("C1", min_prob=0.0)}
        # Khách vừa mua thêm P2 hôm nay -> purchase_count tăng, t_0 về 0, xác suất 7 ngày giảm ngay
        after = {r["product_id"]: r for r in pred.predict_realtime("C1", ["P2"], min_prob=0.0)}
        self.assertEqual(after["P2"]["purchase_count"], before["P2"]["purchase_count"] + 1)
        self.assertEqual(after["P2"]["days_since_last_purchase"], 0)
        self.assertLess(after["P2"]["purchase_probability"], before["P2"]["purchase_probability"])

        # Khách hoàn toàn mới vừa mua P5 hôm nay vẫn trả được dự đoán theo prior
        cold = pred.predict_realtime("NEW_CUST", ["P5"], min_prob=0.0)
        self.assertEqual(len(cold), 1)
        self.assertEqual(cold[0]["product_id"], "P5")
        self.assertEqual(cold[0]["purchase_count"], 1)
        self.assertEqual(cold[0]["days_since_last_purchase"], 0)

    def test_save_and_load_roundtrip(self) -> None:
        pred = NextWeekPredictor(model_type="poisson_gamma").fit(EVENTS)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "next_week" / "predictor.joblib"
            pred.save(path)
            loaded = NextWeekPredictor.load(path)
            self.assertEqual(pred.predict("C1", min_prob=0.0), loaded.predict("C1", min_prob=0.0))


class NextWeekAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cf = CollaborativeFiltering().fit(CF_TRAIN)
        rec = build_recommender(cf, FEATURES, None, current_params(), purchase_events=EVENTS)
        nw = NextWeekPredictor(model_type="ipt_hazard").fit(EVENTS)
        CFModelService.get_instance()._bundle = ModelBundle(
            model=rec,
            cache={},
            next_week=nw,
            source="test",
            version=1,
            stats={**rec.summary(), **nw.summary()},
        )

    def test_health_reports_next_week_model(self) -> None:
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["next_week_model"])
        self.assertEqual(data["next_week_model_type"], "ipt_hazard")

    def test_get_predict_next_week_and_model_override(self) -> None:
        resp = self.client.get("/api/v1/predict/next-week/customer/C1?top_k=5&horizon_days=7&min_prob=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["customer_id"], "C1")
        self.assertEqual(data["horizon_days"], 7)
        self.assertEqual(data["model_type"], "ipt_hazard")
        self.assertEqual(len(data["predictions"]), 3)
        self.assertEqual(data["predictions"][0]["product_id"], "P2")

        # Ghi đè model_type=poisson_gamma qua query param
        resp_pg = self.client.get(
            "/api/v1/predict/next-week/customer/C1?horizon_days=7&min_prob=0&model_type=poisson_gamma"
        )
        self.assertEqual(resp_pg.status_code, 200)
        self.assertEqual(resp_pg.json()["model_type"], "poisson_gamma")
        self.assertEqual(resp_pg.json()["predictions"][0]["reason"], "poisson_gamma")

    def test_post_predict_next_week_realtime(self) -> None:
        resp = self.client.post(
            "/api/v1/predict/next-week",
            json={
                "customer_id": "C1",
                "purchased_product_ids": ["P2"],
                "top_k": 5,
                "horizon_days": 7,
                "min_prob": 0.0,
            },
        )
        self.assertEqual(resp.status_code, 200)
        by_id = {p["product_id"]: p for p in resp.json()["predictions"]}
        self.assertEqual(by_id["P2"]["purchase_count"], 6)
        self.assertEqual(by_id["P2"]["days_since_last_purchase"], 0)

    def test_validation_errors(self) -> None:
        self.assertEqual(
            self.client.get("/api/v1/predict/next-week/customer/C1?horizon_days=0").status_code, 422
        )
        self.assertEqual(
            self.client.get("/api/v1/predict/next-week/customer/C1?min_prob=1.5").status_code, 422
        )
        self.assertEqual(
            self.client.get("/api/v1/predict/next-week/customer/C1?model_type=unknown").status_code, 422
        )

    def test_saved_at_checks_both_models_symmetrically(self) -> None:
        service = CFModelService.get_instance()
        tz = timezone.utc
        with tempfile.TemporaryDirectory() as tmpdir:
            p_rec = Path(tmpdir) / "recommender.joblib"
            p_nw = Path(tmpdir) / "predictor.joblib"
            with patch("api.service.HYBRID_MODEL_PATH", p_rec), \
                 patch("api.service.NEXT_WEEK_MODEL_PATH", p_nw), \
                 patch("api.service.NEXT_WEEK_ENABLED", True):

                # Chưa file nào tồn tại -> None
                self.assertIsNone(service._saved_at(tz))

                # Chỉ có recommender -> None
                p_rec.write_text("dummy")
                self.assertIsNone(service._saved_at(tz))

                # Cả hai tồn tại -> trả về min timestamp
                p_nw.write_text("dummy")
                saved = service._saved_at(tz)
                self.assertIsNotNone(saved)

    def test_fallback_purchase_events_from_df(self) -> None:
        service = CFModelService.get_instance()
        errors: list[str] = []
        with patch("api.service.clickhouse.is_configured", return_value=False):
            # Fallback có DaysSince
            ev1 = service._load_purchase_events(errors, fallback_df=EVENTS)
            self.assertIsNotNone(ev1)
            self.assertEqual(len(ev1), len(EVENTS))
            self.assertIn("CustomerID", ev1.columns)
            self.assertIn("ProductID", ev1.columns)
            self.assertIn("DaysSince", ev1.columns)

            # Fallback có InvoiceDate
            df_dates = pd.DataFrame([
                ("C1", "P1", 2, "2026-11-20 10:00:00"),
                ("C1", "P2", 1, "2026-11-15 10:00:00"),
            ], columns=["CustomerID", "ProductID", "Quantity", "InvoiceDate"])
            ev2 = service._load_purchase_events(errors, fallback_df=df_dates)
            self.assertIsNotNone(ev2)
            self.assertEqual(len(ev2), 2)
            self.assertIn("DaysSince", ev2.columns)

    def test_train_sync_and_post_train_endpoint(self) -> None:
        service = CFModelService.get_instance()
        with tempfile.TemporaryDirectory() as tmpdir:
            p_rec = Path(tmpdir) / "recommender.joblib"
            p_nw = Path(tmpdir) / "predictor.joblib"
            with patch("api.service.HYBRID_MODEL_PATH", p_rec), \
                 patch("api.service.NEXT_WEEK_MODEL_PATH", p_nw), \
                 patch("api.service.NEXT_WEEK_ENABLED", True), \
                 patch.object(service, "_load_frame", return_value=(CF_TRAIN, "mock")), \
                 patch.object(service, "_load_content", return_value=(FEATURES, None)):

                # Chạy train đồng bộ
                bundle = service._train_sync()
                self.assertIsNotNone(bundle)
                self.assertIsNotNone(bundle.model)
                self.assertIsNotNone(bundle.next_week)
                self.assertIn("next_week_pairs", bundle.stats)
                # Cả hai model được ghi ra đĩa
                self.assertTrue(p_rec.exists())
                self.assertTrue(p_nw.exists())

                # Test endpoint POST /api/v1/train
                resp = self.client.post("/api/v1/train")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["status"], "ok")
                self.assertIn("stats", data)
                self.assertIn("next_week_pairs", data["stats"])


if __name__ == "__main__":
    unittest.main()
