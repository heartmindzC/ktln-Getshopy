"""CLI runner for Next-Week Prediction Service."""

import argparse
import json
import logging
from api.service import NextWeekService

logging.basicConfig(level=logging.INFO)


def main():
    parser = argparse.ArgumentParser(description="Next-Week Prediction Service CLI")
    parser.add_argument("--train", action="store_true", help="Huấn luyện mô hình từ ClickHouse")
    parser.add_argument("--customer", type=str, help="ID khách hàng cần dự đoán")
    parser.add_argument("--top-k", type=int, default=10, help="Số sản phẩm dự đoán")
    parser.add_argument("--horizon", type=int, default=7, help="Cửa sổ ngày dự đoán")
    parser.add_argument("--min-prob", type=float, default=0.05, help="Ngưỡng xác suất")
    parser.add_argument("--model-type", type=str, choices=["poisson_gamma", "ipt_hazard"], default=None)

    args = parser.parse_args()
    service = NextWeekService.get_instance()

    if args.train:
        res = service.train()
        print("Kết quả train:", json.dumps(res, indent=2, ensure_ascii=False))

    if args.customer:
        res = service.predict_next_week(
            customer_id=args.customer,
            top_k=args.top_k,
            horizon_days=args.horizon,
            min_prob=args.min_prob,
            model_type=args.model_type,
        )
        print(f"Dự đoán cho khách {args.customer}:")
        print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
