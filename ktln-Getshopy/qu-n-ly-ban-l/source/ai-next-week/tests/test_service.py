"""Unit tests for Next-Week Prediction Service."""

import unittest
import pandas as pd
from fastapi.testclient import TestClient

from api.main import app
from api.service import NextWeekService
from models.next_week import NextWeekPredictor


class TestNextWeekService(unittest.TestCase):
    def setUp(self):
        # Tạo dữ liệu giả lập cho 2 khách hàng
        # Customer 1: mua sp 101 ba lần (DaysSince = 30, 20, 10), sp 102 một lần (DaysSince = 5)
        # Customer 2: mua sp 103 hai lần (DaysSince = 40, 5)
        self.events = pd.DataFrame([
            {"CustomerID": "c1", "ProductID": "101", "DaysSince": 30, "ParentCategory": "cat_a"},
            {"CustomerID": "c1", "ProductID": "101", "DaysSince": 20, "ParentCategory": "cat_a"},
            {"CustomerID": "c1", "ProductID": "101", "DaysSince": 10, "ParentCategory": "cat_a"},
            {"CustomerID": "c1", "ProductID": "102", "DaysSince": 5, "ParentCategory": "cat_b"},
            {"CustomerID": "c2", "ProductID": "103", "DaysSince": 40, "ParentCategory": "cat_a"},
            {"CustomerID": "c2", "ProductID": "103", "DaysSince": 5, "ParentCategory": "cat_a"},
        ])
        self.predictor = NextWeekPredictor(model_type="poisson_gamma").fit(self.events)
        service = NextWeekService.get_instance()
        service._predictor = self.predictor
        self.client = TestClient(app)

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["model_loaded"])
        self.assertEqual(data["customers"], 2)

    def test_predict_customer(self):
        resp = self.client.get("/api/v1/predict/next-week/customer/c1?top_k=5&min_prob=0.0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["customer_id"], "c1")
        self.assertEqual(data["total_purchased_products"], 2)
        self.assertGreaterEqual(len(data["predictions"]), 1)
        self.assertGreaterEqual(len(data["recent_purchases"]), 2)

    def test_predict_realtime(self):
        body = {
            "customer_id": "c1",
            "purchased_product_ids": ["102"],
            "top_k": 5,
            "min_prob": 0.0,
        }
        resp = self.client.post("/api/v1/predict/next-week", json=body)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["customer_id"], "c1")
        self.assertGreaterEqual(len(data["predictions"]), 1)


if __name__ == "__main__":
    unittest.main()
