"""Unit tests for NextWeekPredictor core algorithms."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from models.next_week import NextWeekPredictor

EVENTS = pd.DataFrame([
    {"CustomerID": "C1", "ProductID": "P1", "DaysSince": 100, "ParentCategory": "cat_a"},
    {"CustomerID": "C1", "ProductID": "P1", "DaysSince": 70, "ParentCategory": "cat_a"},
    {"CustomerID": "C1", "ProductID": "P1", "DaysSince": 40, "ParentCategory": "cat_a"},
    {"CustomerID": "C1", "ProductID": "P1", "DaysSince": 10, "ParentCategory": "cat_a"},
    {"CustomerID": "C1", "ProductID": "P2", "DaysSince": 50, "ParentCategory": "cat_b"},
    {"CustomerID": "C1", "ProductID": "P2", "DaysSince": 40, "ParentCategory": "cat_b"},
    {"CustomerID": "C1", "ProductID": "P2", "DaysSince": 30, "ParentCategory": "cat_b"},
    {"CustomerID": "C1", "ProductID": "P2", "DaysSince": 20, "ParentCategory": "cat_b"},
    {"CustomerID": "C1", "ProductID": "P2", "DaysSince": 10, "ParentCategory": "cat_b"},
    {"CustomerID": "C1", "ProductID": "P3", "DaysSince": 5, "ParentCategory": "cat_b"},
    {"CustomerID": "C2", "ProductID": "P1", "DaysSince": 15, "ParentCategory": "cat_a"},
])


class NextWeekPredictorTests(unittest.TestCase):
    def test_fit_and_predict_poisson_gamma(self) -> None:
        pred = NextWeekPredictor(model_type="poisson_gamma").fit(EVENTS)
        items = pred.predict("C1", top_k=5, horizon_days=7.0, min_prob=0.0)
        self.assertEqual(len(items), 3)
        for it in items:
            self.assertIn("product_id", it)
            self.assertGreaterEqual(it["purchase_probability"], 0.0)
            self.assertLessEqual(it["purchase_probability"], 1.0)
            self.assertEqual(it["reason"], "poisson_gamma")
            self.assertIsNotNone(it["expected_cycle_days"])
            self.assertGreater(it["expected_cycle_days"], 0.0)

    def test_fit_and_predict_ipt_hazard(self) -> None:
        pred = NextWeekPredictor(model_type="ipt_hazard").fit(EVENTS)
        items = pred.predict("C1", top_k=5, horizon_days=7.0, min_prob=0.0)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["reason"], "ipt_hazard")

    def test_predict_realtime_boosts_or_adds_item(self) -> None:
        pred = NextWeekPredictor(model_type="poisson_gamma").fit(EVENTS)
        base = {it["product_id"]: it for it in pred.predict("C1", min_prob=0.0)}
        rt = {
            it["product_id"]: it
            for it in pred.predict_realtime("C1", purchased_product_ids=["P2", "P999"], min_prob=0.0)
        }
        self.assertEqual(rt["P2"]["purchase_count"], base["P2"]["purchase_count"] + 1)
        self.assertEqual(rt["P2"]["days_since_last_purchase"], 0)
        self.assertIn("P999", rt)
        self.assertEqual(rt["P999"]["purchase_count"], 1)

    def test_unknown_customer_returns_empty(self) -> None:
        pred = NextWeekPredictor().fit(EVENTS)
        self.assertEqual(pred.predict("UNKNOWN_CUST"), [])
        self.assertEqual(pred.predict_realtime("UNKNOWN_CUST", []), [])
        cold = pred.predict_realtime("UNKNOWN_CUST", ["P1"])
        self.assertEqual(len(cold), 1)
        self.assertEqual(cold[0]["product_id"], "P1")

    def test_save_and_load_roundtrip(self) -> None:
        pred = NextWeekPredictor(model_type="poisson_gamma").fit(EVENTS)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "next_week" / "predictor.joblib"
            pred.save(path)
            loaded = NextWeekPredictor.load(path)
            self.assertEqual(pred.predict("C1", min_prob=0.0), loaded.predict("C1", min_prob=0.0))

    def test_get_purchase_history(self) -> None:
        pred = NextWeekPredictor(model_type="poisson_gamma").fit(EVENTS)
        total, history = pred.get_purchase_history("C1", limit=10)
        self.assertEqual(total, 3)
        self.assertEqual(len(history), 3)
        p_ids = [h["product_id"] for h in history]
        self.assertIn("P1", p_ids)
        self.assertIn("P2", p_ids)
        self.assertIn("P3", p_ids)


if __name__ == "__main__":
    unittest.main()
