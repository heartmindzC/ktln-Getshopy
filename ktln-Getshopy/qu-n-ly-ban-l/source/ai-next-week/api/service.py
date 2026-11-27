"""Service orchestrating loading, training, and predicting with NextWeekPredictor."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone, tzinfo
from typing import Any

from config import (
    DEFAULT_TOP_K,
    NEXT_WEEK_DEFAULT_HORIZON_DAYS,
    NEXT_WEEK_DEFAULT_MIN_PROB,
    NEXT_WEEK_MODEL_PATH,
    NEXT_WEEK_MODEL_TYPE,
    NEXT_WEEK_REFERENCE_MODE,
    TRAIN_DAILY_AT,
    TRAIN_INTERVAL_SECONDS,
    TRAIN_TIMEZONE,
)
from api import schedule
from data_source import clickhouse
from models.next_week import NextWeekPredictor

logger = logging.getLogger(__name__)


class NextWeekService:
    """Singleton service cho dự đoán xác suất mua lại trong W ngày tới."""

    _instance: NextWeekService | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._predictor: NextWeekPredictor | None = None
        self._task: asyncio.Task | None = None
        self._trained_at: str | None = None
        self._model_version: int = 0
        self._last_error: str | None = None
        self._train_lock = threading.Lock()

        # Thử nạp model từ ổ đĩa lúc khởi động
        self._load_from_disk()

    @classmethod
    def get_instance(cls) -> NextWeekService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _saved_at(self, tz: tzinfo) -> datetime | None:
        if not NEXT_WEEK_MODEL_PATH.exists():
            return None
        try:
            mtime = NEXT_WEEK_MODEL_PATH.stat().st_mtime
            return datetime.fromtimestamp(mtime, tz=timezone.utc).astimezone(tz)
        except OSError:
            return None

    def _load_from_disk(self) -> None:
        if not NEXT_WEEK_MODEL_PATH.exists():
            logger.info("Chưa có checkpoint model tại %s", NEXT_WEEK_MODEL_PATH)
            return
        try:
            predictor = NextWeekPredictor.load(NEXT_WEEK_MODEL_PATH)
            self._predictor = predictor
            self._model_version += 1
            self._trained_at = datetime.fromtimestamp(
                NEXT_WEEK_MODEL_PATH.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            logger.info("Đã nạp NextWeekPredictor từ %s: %s", NEXT_WEEK_MODEL_PATH, predictor.summary())
        except Exception as exc:
            self._last_error = f"Không đọc được model từ đĩa: {exc}"
            logger.warning("%s", self._last_error)

    def train_sync(self) -> dict[str, Any]:
        """Huấn luyện đồng bộ mô hình từ ClickHouse và lưu ra đĩa."""
        if not self._train_lock.acquire(blocking=False):
            return {"status": "in_progress", "message": "Quá trình train khác đang chạy."}

        try:
            logger.info("Bắt đầu train NextWeekPredictor từ ClickHouse...")
            events = clickhouse.fetch_purchase_events()
            categories = clickhouse.fetch_product_categories()

            predictor = NextWeekPredictor(
                model_type=NEXT_WEEK_MODEL_TYPE,
                reference_mode=NEXT_WEEK_REFERENCE_MODE,
            )
            predictor.fit(events, product_categories=categories)

            # Lưu ra đĩa
            NEXT_WEEK_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            predictor.save(NEXT_WEEK_MODEL_PATH)

            # Hoán đổi con trỏ atomic
            self._predictor = predictor
            self._model_version += 1
            self._trained_at = datetime.now(timezone.utc).isoformat()
            self._last_error = None
            summary = predictor.summary()
            logger.info("Train NextWeekPredictor hoàn tất: %s", summary)
            return {"status": "success", "summary": summary}
        except Exception as exc:
            self._last_error = str(exc)
            logger.error("Lỗi khi train NextWeekPredictor: %s", exc, exc_info=True)
            return {"status": "failed", "error": str(exc)}
        finally:
            self._train_lock.release()

    async def _train_guarded(self) -> None:
        await asyncio.to_thread(self.train_sync)

    async def _training_loop(self) -> None:
        await asyncio.sleep(5)  # Delay khởi động 5s
        if not TRAIN_DAILY_AT:
            while True:
                await self._train_guarded()
                await asyncio.sleep(TRAIN_INTERVAL_SECONDS)

        try:
            hour, minute = schedule.parse_hhmm(TRAIN_DAILY_AT)
        except ValueError as exc:
            logger.error("Sai cấu hình TRAIN_DAILY_AT: %s", exc)
            return

        tz = schedule.get_tz(TRAIN_TIMEZONE)
        saved_at = self._saved_at(tz)
        if schedule.missed(saved_at, datetime.now(tz), hour, minute):
            logger.info("Model trên đĩa trước mốc %s gần nhất: train bù ngay.", TRAIN_DAILY_AT)
            await self._train_guarded()

        while True:
            target = schedule.next_run(datetime.now(tz), hour, minute)
            logger.info("Lượt train kế tiếp: %s", target.isoformat(timespec="minutes"))
            while (remaining := (target - datetime.now(tz)).total_seconds()) > 0:
                await asyncio.sleep(min(remaining, 300))
            await self._train_guarded()

    def start_background_loop(self) -> None:
        if self._task is not None:
            return
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._training_loop())

    async def stop_background_loop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    def health(self) -> dict[str, Any]:
        """Thông tin tình trạng sức khỏe dịch vụ."""
        loaded = self._predictor is not None
        summary = self._predictor.summary() if loaded else {}
        return {
            "status": "ok",
            "model_name": "Next-Week Purchase Predictor",
            "model_loaded": loaded,
            "version": "1.0.0",
            "model_version": self._model_version,
            "trained_at": self._trained_at,
            "model_type": summary.get("next_week_model_type", NEXT_WEEK_MODEL_TYPE),
            "customers": summary.get("next_week_customers", 0),
            "pairs": summary.get("next_week_pairs", 0),
            "categories": summary.get("next_week_categories", 0),
            "last_error": self._last_error,
        }

    def predict_next_week(
        self,
        customer_id: str,
        top_k: int = DEFAULT_TOP_K,
        horizon_days: int = NEXT_WEEK_DEFAULT_HORIZON_DAYS,
        min_prob: float = NEXT_WEEK_DEFAULT_MIN_PROB,
        model_type: str | None = None,
    ) -> dict[str, Any]:
        cid = str(customer_id)
        if self._predictor is None:
            return {
                "customer_id": cid,
                "horizon_days": horizon_days,
                "model_type": model_type or NEXT_WEEK_MODEL_TYPE,
                "total_purchased_products": 0,
                "recent_purchases": [],
                "predictions": [],
            }

        total_purchased, recent_purchases = self._predictor.get_purchase_history(cid, limit=50)
        chosen = model_type or self._predictor.model_type
        items = self._predictor.predict(
            customer_id=cid,
            top_k=top_k,
            horizon_days=float(horizon_days),
            min_prob=float(min_prob),
            model_type=chosen,
        )
        return {
            "customer_id": cid,
            "horizon_days": horizon_days,
            "model_type": chosen,
            "total_purchased_products": total_purchased,
            "recent_purchases": recent_purchases,
            "predictions": items,
        }

    def predict_next_week_realtime(
        self,
        customer_id: str,
        purchased_product_ids: list[str],
        top_k: int = DEFAULT_TOP_K,
        horizon_days: int = NEXT_WEEK_DEFAULT_HORIZON_DAYS,
        min_prob: float = NEXT_WEEK_DEFAULT_MIN_PROB,
        model_type: str | None = None,
    ) -> dict[str, Any]:
        cid = str(customer_id)
        if self._predictor is None:
            return {
                "customer_id": cid,
                "horizon_days": horizon_days,
                "model_type": model_type or NEXT_WEEK_MODEL_TYPE,
                "total_purchased_products": 0,
                "recent_purchases": [],
                "predictions": [],
            }

        total_purchased, recent_purchases = self._predictor.get_purchase_history(cid, limit=50)
        chosen = model_type or self._predictor.model_type
        items = self._predictor.predict_realtime(
            customer_id=cid,
            purchased_product_ids=purchased_product_ids,
            top_k=top_k,
            horizon_days=float(horizon_days),
            min_prob=float(min_prob),
            model_type=chosen,
        )
        return {
            "customer_id": cid,
            "horizon_days": horizon_days,
            "model_type": chosen,
            "total_purchased_products": total_purchased,
            "recent_purchases": recent_purchases,
            "predictions": items,
        }
