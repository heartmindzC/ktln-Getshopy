"""Pydantic schemas for Next-Week Prediction API."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from config import (
    DEFAULT_TOP_K,
    NEXT_WEEK_DEFAULT_HORIZON_DAYS,
    NEXT_WEEK_DEFAULT_MIN_PROB,
    NEXT_WEEK_MAX_RECENT_PURCHASES,
)


class CustomerPurchaseHistoryItem(BaseModel):
    """Thông tin một sản phẩm khách hàng đã từng mua trong lịch sử."""

    product_id: str = Field(..., description="Mã sản phẩm (ProductID)")
    days_since_last_purchase: int = Field(..., ge=0, description="Số ngày kể từ lần mua gần nhất")
    purchase_count: int = Field(..., ge=1, description="Tổng số lần đã mua sản phẩm này")


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
    total_purchased_products: int = Field(0, description="Tổng số sản phẩm khách hàng đã từng mua")
    recent_purchases: list[CustomerPurchaseHistoryItem] = Field(
        default_factory=list, description="Lịch sử các sản phẩm khách đã mua và thời gian mua gần nhất"
    )
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
    model_name: str = Field("Next-Week Purchase Predictor", example="Next-Week Purchase Predictor")
    model_loaded: bool = Field(...)
    version: str = Field("1.0.0", example="1.0.0")
    model_version: int = Field(0, description="Số thứ tự bản train")
    trained_at: str | None = Field(None, description="Thời điểm train xong (UTC)")
    model_type: str | None = Field(None, description="poisson_gamma | ipt_hazard")
    customers: int = Field(0, description="Số khách hàng trong mô hình")
    pairs: int = Field(0, description="Số cặp (khách, sản phẩm) được theo dõi")
    categories: int = Field(0, description="Số danh mục có tham số prior")
    last_error: str | None = Field(None, description="Lỗi của lần train gần nhất")


class TrainTriggerResponse(BaseModel):
    """Phản hồi sau khi kích hoạt huấn luyện."""

    status: str
    message: str
