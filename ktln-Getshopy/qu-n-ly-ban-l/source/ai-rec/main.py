"""Command-line entry point for querying recommendations by customer ID (CustomerID) or order ID (InvoiceNo)."""

from __future__ import annotations

import argparse
import sys

from config import DEFAULT_TOP_K
from models import CollaborativeFiltering


def print_header() -> None:
    print("=" * 65)
    print("      HỆ THỐNG GỢI Ý SẢN PHẨM AI - ECOMMERCE RECOMMENDER")
    print("=" * 65)


def display_customer_recommendations(
    model: CollaborativeFiltering, customer_id: str, top_k: int
) -> None:
    """Hiển thị gợi ý sản phẩm cho một Customer ID cụ thể kèm lịch sử mua hàng và tên sản phẩm."""
    cust_info = model.customer_details(customer_id)
    cust_name = cust_info.get("CustomerName", "Khách hàng")
    purchased = model.get_purchased_products(customer_id)
    recommendations = model.recommend(customer_id, top_k=top_k)

    print(f"\n👤 THÔNG TIN KHÁCH HÀNG: {customer_id} - {cust_name}")
    if purchased:
        print(f"   • Lịch sử các sản phẩm đã mua ({len(purchased)} sản phẩm):")
        for idx, prod_id in enumerate(purchased, start=1):
            details = model.product_details(prod_id)
            prod_name = details.get("ProductName", prod_id)
            cat = details.get("Category", "N/A")
            price = float(details.get("UnitPrice", 0))
            print(f"     {idx:2d}. [{prod_id}] {prod_name:<48} | {cat:<10} | Đơn giá: {price:,.0f} VNĐ")
    else:
        print("   • Khách hàng mới (Cold-Start): Chưa có lịch sử giao dịch.")

    print(f"\n🤖 GỢI Ý SẢN PHẨM PHÙ HỢP TỪ AI MODEL (TOP {top_k}):")
    if not recommendations:
        print(f"   Không có gợi ý sản phẩm cho khách hàng {customer_id!r}.")
        return

    for rank, (product_id, score) in enumerate(recommendations, start=1):
        details = model.product_details(product_id)
        prod_name = details.get("ProductName", product_id)
        category = details.get("Category", "Chưa xác định")
        price = float(details.get("UnitPrice", 0))
        print(f"   {rank:2d}. [{product_id}] {prod_name:<48} | {category:<10} | Đơn giá: {price:,.0f} VNĐ | Score: {score:.4f}")


def display_next_week_predictions(customer_id: str, top_k: int) -> None:
    """Hiển thị dự đoán các sản phẩm khách có xác suất mua trong 7 ngày tới."""
    from config import NEXT_WEEK_MODEL_PATH
    from models.next_week import NextWeekPredictor
    if not NEXT_WEEK_MODEL_PATH.exists():
        print("\n⚠️ Chưa có artifact Next-Week Predictor trên đĩa (chạy với --train-next-week để huấn luyện).")
        return
    try:
        nw = NextWeekPredictor.load(NEXT_WEEK_MODEL_PATH)
        preds = nw.predict(customer_id, top_k=top_k, horizon_days=7)
        print(f"\n🔮 DỰ ĐOÁN MUA LẶP LẠI TRONG 7 NGÀY TỚI (NEXT-WEEK AI):")
        if not preds:
            print(f"   Không có sản phẩm nào vượt ngưỡng xác suất mua trong 7 ngày tới cho khách {customer_id!r}.")
            return
        for rank, item in enumerate(preds, start=1):
            pid = item["product_id"]
            prob = item["purchase_probability"] * 100
            count = item["purchase_count"]
            days = item["days_since_last_purchase"]
            cycle = item.get("expected_cycle_days")
            cycle_str = f"{cycle:.1f} ngày" if cycle else "N/A"
            print(f"   {rank:2d}. [{pid}] Xác suất: {prob:5.1f}% | Đã mua: {count} lần | Cách đây: {days} ngày | Chu kỳ: {cycle_str}")
    except Exception as exc:
        print(f"⚠️ Không thể tải mô hình Next-Week: {exc}")


def display_invoice_recommendations(
    model: CollaborativeFiltering, invoice_id: str, top_k: int
) -> None:
    """Tra cứu đơn hàng và hiển thị thông tin kèm gợi ý sản phẩm từ mô hình AI."""
    order_info, recommendations = model.recommend_by_invoice(invoice_id, top_k=top_k)

    if not order_info:
        print(f"\n❌ Không tìm thấy thông tin cho mã đơn hàng '{invoice_id}'.")
        print("💡 Gợi ý: Bạn có thể kiểm tra lại mã đơn hàng trong tập dữ liệu (Ví dụ: INV004935, INV008706).")
        return

    customer_id = str(order_info["customer_id"])
    cust_info = model.customer_details(customer_id)
    cust_name = cust_info.get("CustomerName", "Khách hàng")

    print(f"\n📦 THÔNG TIN ĐƠN HÀNG: {order_info['invoice_id']}")
    print(f"   • Khách hàng: {customer_id} - {cust_name}")
    print(f"   • Các sản phẩm đã mua trong đơn hàng:")

    items = order_info.get("items", [])
    for idx, item in enumerate(items, start=1):
        prod_id = item.get("ProductID", "N/A")
        prod_name = item.get("ProductName", prod_id)
        category = item.get("Category", "N/A")
        quantity = item.get("Quantity", 1)
        price = float(item.get("UnitPrice", 0))
        print(f"     {idx}. [{prod_id}] {prod_name:<48} | {category:<10} | SL: {quantity:<2} | Đơn giá: {price:,.0f} VNĐ")

    print(f"   • Tổng giá trị đơn hàng: {order_info['total_amount']:,.0f} VNĐ")

    print(f"\n🤖 GỢI Ý SẢN PHẨM PHÙ HỢP TỪ AI MODEL (TOP {top_k}):")
    if not recommendations:
        print("   Không có gợi ý sản phẩm nào khả thi.")
        return

    for rank, (product_id, score) in enumerate(recommendations, start=1):
        details = model.product_details(product_id)
        prod_name = details.get("ProductName", product_id)
        category = details.get("Category", "Chưa xác định")
        price = float(details.get("UnitPrice", 0))
        print(f"   {rank:2d}. [{product_id}] {prod_name:<48} | {category:<10} | Đơn giá: {price:,.0f} VNĐ | Score: {score:.4f}")


def main() -> None:
    # --------------------------------------------------------------------------
    # 1. Định nghĩa tham số dòng lệnh (CLI Arguments)
    # --------------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description="Gợi ý sản phẩm bằng Collaborative Filtering."
    )
    parser.add_argument(
        "-c",
        "--customer-id",
        dest="customer_id",
        help="Mã khách hàng (CustomerID) cần nhận gợi ý.",
    )
    parser.add_argument(
        "-i",
        "--invoice-id",
        "--order-id",
        dest="invoice_id",
        help="Mã đơn hàng (InvoiceNo) cần tra cứu và nhận gợi ý.",
    )
    parser.add_argument(
        "-k",
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Số lượng sản phẩm gợi ý (Mặc định: {DEFAULT_TOP_K}).",
    )
    parser.add_argument(
        "--load-model",
        action="store_true",
        help="Nạp mô hình đã lưu từ đĩa thay vì huấn luyện lại.",
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Bỏ qua artifact hiện có và huấn luyện lại mô hình.",
    )
    parser.add_argument(
        "--train-next-week",
        action="store_true",
        help="Huấn luyện mô hình Next-Week Predictor và lưu artifact ra đĩa.",
    )
    parser.add_argument(
        "--next-week",
        action="store_true",
        help="Hiển thị thêm dự đoán mua lặp lại trong 7 ngày tới khi tra cứu khách hàng.",
    )
    args = parser.parse_args()

    # --------------------------------------------------------------------------
    # 2. Tải hoặc huấn luyện mô hình AI
    # --------------------------------------------------------------------------
    model = CollaborativeFiltering()
    if args.load_model or (model.model_path.exists() and not args.retrain and not args.train_next_week):
        model.load_model()
    elif not args.train_next_week:
        print("Huấn luyện mô hình COLLABORATIVE FILTERING...")
        model.train()
        model.save_model()
        print(f"Mô hình đã được lưu tại: {model.model_path}")

    # Huấn luyện Next-Week Predictor nếu được yêu cầu qua --train-next-week hoặc --retrain
    if args.train_next_week or args.retrain:
        from config import NEXT_WEEK_MODEL_PATH
        print("Huấn luyện mô hình NEXT-WEEK PREDICTOR...")
        try:
            from api.service import CFModelService
            service = CFModelService.get_instance()
            df, _ = service._load_frame()
            if df is not None and not df.empty:
                errors: list[str] = []
                events = service._load_purchase_events(errors, fallback_df=df)
                features, _ = service._load_content(errors)
                nw = service._fit_next_week(events, features, errors)
                if nw is not None:
                    service._persist_next_week(nw)
                    print(f"Mô hình Next-Week đã được lưu tại: {NEXT_WEEK_MODEL_PATH}")
                    print(f"📊 Thông số Next-Week: {nw.summary()}")
                else:
                    print("⚠️ Không đủ dữ liệu purchase_events để huấn luyện Next-Week Predictor.")
            else:
                print("⚠️ Không tìm thấy dữ liệu đơn hàng để huấn luyện Next-Week.")
        except Exception as exc:
            print(f"⚠️ Lỗi khi huấn luyện Next-Week Predictor: {exc}")

    # --------------------------------------------------------------------------
    # 3. Xử lý luồng tương tác nhập mã khách hàng nếu không truyền CLI argument
    # --------------------------------------------------------------------------
    customer_id = args.customer_id
    invoice_id = args.invoice_id

    if not customer_id and not invoice_id:
        print_header()
        print(f"📊 Thông số mô hình: {model.summary()['customers']} khách hàng | "
              f"{model.summary()['products']} sản phẩm | "
              f"{model.summary()['interactions']} tương tác")
        print("-" * 65)

        while True:
            try:
                user_input = input("👉 Nhập mã khách hàng (CustomerID) [Ví dụ: CUST_0001]: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nĐã hủy thao tác.")
                sys.exit(0)

            if not user_input:
                print("⚠️ Bạn chưa nhập mã. Chương trình kết thúc.")
                return

            if user_input.upper().startswith("INV"):
                invoice_id = user_input
            else:
                customer_id = user_input

            if user_input.upper() == "QUIT" or user_input.upper() == "EXIT":
                break

            if customer_id:
                display_customer_recommendations(model, customer_id, top_k=args.top_k)
                if args.next_week:
                    display_next_week_predictions(customer_id, top_k=args.top_k)
            elif invoice_id:
                display_invoice_recommendations(model, invoice_id, top_k=args.top_k)

    # --------------------------------------------------------------------------
    # 4. Đưa ra gợi ý theo Mã khách hàng hoặc Mã đơn hàng
    # --------------------------------------------------------------------------
    if customer_id:
        display_customer_recommendations(model, customer_id, top_k=args.top_k)
        if args.next_week:
            display_next_week_predictions(customer_id, top_k=args.top_k)
    elif invoice_id:
        display_invoice_recommendations(model, invoice_id, top_k=args.top_k)


# ------------------------------------------------------------------------------
# Điểm khởi chạy chương trình khi gọi trực tiếp file main.py
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
