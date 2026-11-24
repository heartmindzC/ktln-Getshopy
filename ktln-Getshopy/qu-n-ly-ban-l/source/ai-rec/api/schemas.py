"""Pydantic request and response schemas for Recommendation API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from config import (
    DEFAULT_TOP_K,
    NEXT_WEEK_DEFAULT_HORIZON_DAYS,
    NEXT_WEEK_DEFAULT_MIN_PROB,
    NEXT_WEEK_MAX_RECENT_PURCHASES,
    REALTIME_MAX_INTERACTIONS,
    REALTIME_MAX_PURCHASES,
)


class BehaviorInteractionItem(BaseModel):
    """Một tương tác hành vi đơn lẻ của khách hàng trong phiên duyệt web.

    Nhận mã món (product_id), loại sự kiện (view, cart, wish, purchase), và thời gian
    nán lại trang tính bằng giây (dwell_seconds, tối đa 600s = 10 phút, chỉ cho view).
    """

    model_config = ConfigDict(coerce_numbers_to_str=True)

    product_id: str = Field(..., min_length=1, max_length=64, description="Mã sản phẩm (ProductID)")
    event_type: str = Field(
        ...,
        description="Loại sự kiện: view | cart | wish | purchase (hoặc product_view, add_to_cart, add_to_wishlist)",
    )
    dwell_seconds: float | None = Field(
        None,
        ge=0,
        le=600,
        description="Thời gian nán lại trang xem sản phẩm (giây, trần 600s = 10 phút). Áp dụng cho event_type = view",
    )


class RealtimeBehaviorRecommendationRequest(BaseModel):
    """Body của POST /api/v1/recommend/realtime-behavior (15/11/2026).

    Nhận mã món đã mua (như /realtime) KÈM danh sách các tương tác hành vi chi tiết
    (view kèm dwell time, cart, wishlist) phát sinh từ mốc train gần nhất đến nay.
    """

    model_config = ConfigDict(coerce_numbers_to_str=True)

    customer_id: str = Field(..., min_length=1, max_length=64, description="Mã khách hàng (CustomerID)")
    purchased_product_ids: list[str] = Field(
        default_factory=list,
        max_length=REALTIME_MAX_PURCHASES,
        description="Mã các món khách đã mua tới lúc gọi (đơn thanh toán, không huỷ)",
    )
    interactions: list[BehaviorInteractionItem] = Field(
        default_factory=list,
        max_length=REALTIME_MAX_INTERACTIONS,
        description="Danh sách tương tác hành vi gần đây trong phiên (xem, giỏ hàng, yêu thích)",
    )
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=50, description="Số lượng sản phẩm đề xuất tối đa")


class RealtimeRecommendationRequest(BaseModel):
    """Body của POST /api/v1/recommend/realtime (12/11/2026).

    Chỉ nhận MÃ món đã mua — đơn đã thanh toán, không huỷ, đúng định nghĩa của tập
    train (dbt purchase_events_for_AI_rec) — chưa nhận hành vi xem/giỏ: phạm vi
    giai đoạn 1 người dùng đã duyệt.
    """

    # Server Node đọc product_id từ Postgres (BigInt): gửi số thay vì chuỗi cũng phải
    # được nhận, vì mã chỉ dùng để tra như chuỗi — đúng cách tập train ép toString().
    model_config = ConfigDict(coerce_numbers_to_str=True)

    customer_id: str = Field(..., min_length=1, max_length=64, description="Mã khách hàng (CustomerID)")
    purchased_product_ids: list[str] = Field(
        default_factory=list,
        max_length=REALTIME_MAX_PURCHASES,
        description="Mã các món khách đã mua tới lúc gọi (mới nhất trước). Món bản train "
                    "đã biết giữ trọng số cũ; mã lạ (món mới tinh) bị bỏ qua.",
    )
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=50, description="Số lượng sản phẩm đề xuất tối đa")


class RecommendationItem(BaseModel):
    """Chi tiết của một sản phẩm được gợi ý."""

    product_id: str = Field(..., description="Mã sản phẩm (ProductID)")
    # Kênh đóng góp nhiều nhất vào điểm của món — để giao diện giải thích được
    # "vì sao gợi ý món này". Có giá trị mặc định: bên gọi cũ bỏ qua được.
    reason: str | None = Field(
        None, description="cf | content | repeat | popular — kênh chính đưa món này lên"
    )


class CustomerRecommendationResponse(BaseModel):
    """Kết quả gợi ý sản phẩm cho một khách hàng."""

    customer_id: str = Field(..., description="Mã khách hàng")
    recommendations: list[RecommendationItem] = Field(
        default_factory=list, description="Danh sách sản phẩm được AI đề xuất"
    )


class NextWeekPredictionItem(BaseModel):
    """Một sản phẩm dự đoán sẽ được khách hàng mua trong W ngày tới."""

    product_id: str = Field(..., description="Mã sản phẩm (ProductID)")
    purchase_probability: float = Field(
        ..., ge=0.0, le=1.0, description="Xác suất khách mua lại sản phẩm này trong cửa sổ W ngày tới"
    )
    expected_cycle_days: float | None = Field(
        None, description="Chu kỳ mua lặp lại kỳ vọng của khách với món này (ngày)"
    )
    days_since_last_purchase: int = Field(
        ..., ge=0, description="Số ngày đã trôi qua kể từ lần mua gần nhất"
    )
    purchase_count: int = Field(..., ge=1, description="Tổng số đơn khách đã mua sản phẩm này")
    reason: str = Field(..., description="Mô hình xác suất đã tính: poisson_gamma | ipt_hazard")


class NextWeekPredictionResponse(BaseModel):
    """Kết quả dự đoán mua hàng trong W ngày tới cho một khách hàng."""

    customer_id: str = Field(..., description="Mã khách hàng")
    horizon_days: int = Field(..., description="Độ dài cửa sổ dự đoán (ngày)")
    model_type: str | None = Field(None, description="Biến thể mô hình đã dùng: poisson_gamma | ipt_hazard")
    predictions: list[NextWeekPredictionItem] = Field(
        default_factory=list, description="Danh sách sản phẩm theo xác suất mua giảm dần"
    )


class NextWeekRealtimePredictionRequest(BaseModel):
    """Body của POST /api/v1/predict/next-week (ghép thêm đơn mua trong ngày)."""

    model_config = ConfigDict(coerce_numbers_to_str=True)

    customer_id: str = Field(..., min_length=1, max_length=64, description="Mã khách hàng (CustomerID)")
    purchased_product_ids: list[str] = Field(
        default_factory=list,
        max_length=NEXT_WEEK_MAX_RECENT_PURCHASES,
        description="Mã các món khách mới mua trong ngày (DaysSince = 0)",
    )
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=50, description="Số sản phẩm trả về tối đa")
    horizon_days: int = Field(
        NEXT_WEEK_DEFAULT_HORIZON_DAYS, ge=1, le=90, description="Cửa sổ dự đoán (ngày)"
    )
    min_prob: float = Field(
        NEXT_WEEK_DEFAULT_MIN_PROB, ge=0.0, le=1.0, description="Ngưỡng xác suất tối thiểu"
    )
    model_type: Literal["poisson_gamma", "ipt_hazard"] | None = Field(
        None, description="Tuỳ chọn ghi đè biến thể mô hình: poisson_gamma | ipt_hazard"
    )


class HealthResponse(BaseModel):
    """Trạng thái sức khỏe dịch vụ và thông số mô hình."""

    status: str = Field(..., example="ok")
    model_name: str = Field(..., example="Item-based Collaborative Filtering")
    model_loaded: bool = Field(...)
    customers: int = Field(..., description="Tổng số khách hàng trong mô hình")
    products: int = Field(..., description="Tổng số sản phẩm trong mô hình")
    interactions: int = Field(..., description="Tổng số tương tác giao dịch")
    version: str = Field(..., example="0.1.0")
    # ── Thông tin vòng đời model ────────────────────────────────────────
    # Thêm ở cuối và đều có giá trị mặc định: bên gọi cũ (server Node) đọc theo
    # tên trường nên thêm trường mới không làm hỏng gì.
    model_version: int = Field(0, description="Số thứ tự bản train, tăng sau mỗi lần swap")
    trained_at: str | None = Field(None, description="Thời điểm train xong (UTC)")
    data_source: str | None = Field(None, description="clickhouse | csv | disk")
    cached_customers: int = Field(0, description="Số khách đã có gợi ý tính sẵn")
    candidates: int = Field(0, description="Số món ứng viên (đang bán, có đặc trưng)")
    onboarded_customers: int = Field(0, description="Số khách có tín hiệu onboarding")
    content_based: bool = Field(False, description="False = đang chạy thuần CF (thiếu bảng đặc trưng)")
    repeat_model: bool = Field(
        False, description="True = kênh mua lại theo tần suất đơn; False = cách cũ (trọng số ma trận CF)"
    )
    behavior: bool = Field(
        False, description="True = ma trận hồ sơ CF có tín hiệu hành vi phụ (xem/giỏ/yêu thích)"
    )
    next_week_model: bool = Field(
        False, description="True = mô hình dự đoán mua trong 7 ngày tới đã sẵn sàng"
    )
    next_week_model_type: str | None = Field(
        None, description="Biến thể mô hình dự đoán 7 ngày đang chạy (poisson_gamma | ipt_hazard)"
    )
    last_error: str | None = Field(None, description="Lỗi của lần train gần nhất, nếu có")
