"""FastAPI application for Next-Week Purchase Prediction Service."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import (
    HealthResponse,
    NextWeekPredictionResponse,
    NextWeekRealtimePredictionRequest,
    TrainTriggerResponse,
)
from api.service import NextWeekService
from config import (
    DEFAULT_TOP_K,
    NEXT_WEEK_DEFAULT_HORIZON_DAYS,
    NEXT_WEEK_DEFAULT_MIN_PROB,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_next_week")


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = NextWeekService.get_instance()
    service.start_background_loop()
    yield
    await service.stop_background_loop()


root_path = os.getenv("ROOT_PATH", "")

app = FastAPI(
    title="Next-Week Purchase Prediction Service",
    description=(
        "Độc lập dự đoán xác suất khách hàng mua lại từng sản phẩm trong cửa sổ W ngày tới "
        "(Poisson-Gamma Empirical Bayes / Log-Normal IPT Hazard)."
    ),
    version="1.0.0",
    root_path=root_path,
    servers=[{"url": "/next-week"}, {"url": "/"}] if not root_path else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Kiểm tra trạng thái dịch vụ và mô hình",
)
def get_health() -> HealthResponse:
    service = NextWeekService.get_instance()
    return HealthResponse(**service.health())


@app.get(
    "/api/v1/predict/next-week/customer/{customer_id}",
    response_model=NextWeekPredictionResponse,
    tags=["Predictions"],
    summary="Dự đoán các sản phẩm khách có xác suất mua lại cao nhất trong W ngày tới",
)
def predict_next_week_for_customer(
    customer_id: str = Path(..., description="ID của khách hàng (CustomerID)"),
    top_k: int = Query(DEFAULT_TOP_K, ge=1, le=50, description="Số sản phẩm trả về tối đa"),
    horizon_days: int = Query(
        NEXT_WEEK_DEFAULT_HORIZON_DAYS, ge=1, le=90, description="Cửa sổ dự đoán (ngày, mặc định 7)"
    ),
    min_prob: float = Query(
        NEXT_WEEK_DEFAULT_MIN_PROB, ge=0.0, le=1.0, description="Ngưỡng xác suất tối thiểu"
    ),
    model_type: Literal["poisson_gamma", "ipt_hazard"] | None = Query(
        None, description="Tuỳ chọn ghi đè biến thể mô hình: poisson_gamma | ipt_hazard"
    ),
) -> NextWeekPredictionResponse:
    service = NextWeekService.get_instance()
    try:
        data = service.predict_next_week(
            customer_id=customer_id,
            top_k=top_k,
            horizon_days=horizon_days,
            min_prob=min_prob,
            model_type=model_type,
        )
        return NextWeekPredictionResponse(**data)
    except Exception as exc:
        logger.error("Lỗi khi dự đoán cho khách %s: %s", customer_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(
    "/api/v1/predict/next-week",
    response_model=NextWeekPredictionResponse,
    tags=["Predictions"],
    summary="Dự đoán mua lại trong W ngày tới kèm đơn vừa mua trong ngày",
)
def predict_next_week_realtime(
    body: NextWeekRealtimePredictionRequest,
) -> NextWeekPredictionResponse:
    service = NextWeekService.get_instance()
    try:
        data = service.predict_next_week_realtime(
            customer_id=body.customer_id,
            purchased_product_ids=body.purchased_product_ids,
            top_k=body.top_k,
            horizon_days=body.horizon_days,
            min_prob=body.min_prob,
            model_type=body.model_type,
        )
        return NextWeekPredictionResponse(**data)
    except Exception as exc:
        logger.error("Lỗi khi dự đoán realtime cho khách %s: %s", body.customer_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(
    "/admin/train",
    response_model=TrainTriggerResponse,
    tags=["Admin"],
    summary="Kích hoạt huấn luyện lại mô hình từ ClickHouse",
)
def trigger_train(background_tasks: BackgroundTasks) -> TrainTriggerResponse:
    service = NextWeekService.get_instance()
    background_tasks.add_task(service.train_sync)
    return TrainTriggerResponse(
        status="accepted",
        message="Quá trình huấn luyện NextWeekPredictor đã được bắt đầu ở chế độ nền.",
    )
