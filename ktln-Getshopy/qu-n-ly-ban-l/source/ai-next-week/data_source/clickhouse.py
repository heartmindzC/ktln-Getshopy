"""Đọc dữ liệu lịch sử đơn hàng từ ClickHouse cho Next-Week service."""

from __future__ import annotations

import io
import logging
import httpx
import pandas as pd

from config import (
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_TIMEOUT_SECONDS,
    CLICKHOUSE_URL,
    CLICKHOUSE_USER,
    PURCHASE_EVENTS_QUERY,
    CATALOG_FEATURES_QUERY,
)

logger = logging.getLogger(__name__)


class ClickHouseUnavailable(RuntimeError):
    """Không lấy được dữ liệu từ warehouse ở lần thử này."""


def is_configured() -> bool:
    return bool(CLICKHOUSE_URL)


def _query(sql: str, dtype: dict[str, str]) -> pd.DataFrame:
    if not is_configured():
        raise ClickHouseUnavailable("Chưa cấu hình CLICKHOUSE_URL")

    try:
        response = httpx.post(
            f"{CLICKHOUSE_URL}/",
            content=sql.encode("utf-8"),
            headers={
                "X-ClickHouse-User": CLICKHOUSE_USER,
                "X-ClickHouse-Key": CLICKHOUSE_PASSWORD,
            },
            timeout=CLICKHOUSE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ClickHouseUnavailable(f"Không gọi được ClickHouse: {exc}") from exc

    if response.status_code != 200:
        raise ClickHouseUnavailable(
            f"ClickHouse trả {response.status_code}: {response.text[:300]}"
        )
    return pd.read_csv(io.StringIO(response.text), sep="\t", dtype=dtype)


def fetch_purchase_events() -> pd.DataFrame:
    """Lấy toàn bộ lịch sử mua theo đơn cho dự đoán chu kỳ mua lại."""
    df = _query(
        PURCHASE_EVENTS_QUERY,
        dtype={"CustomerID": "string", "ProductID": "string", "DaysSince": "int32", "ParentCategory": "string"},
    )
    missing = [c for c in ["CustomerID", "ProductID", "DaysSince"] if c not in df.columns]
    if missing:
        raise ClickHouseUnavailable(f"Lịch sử mua thiếu cột: {missing}")
    logger.info("Đã lấy %d lượt mua của %d khách hàng.", len(df), df["CustomerID"].nunique())
    return df


def fetch_product_categories() -> dict[str, str]:
    """Lấy ánh xạ ProductID -> ParentCategory."""
    try:
        df = _query(
            CATALOG_FEATURES_QUERY,
            dtype={"ProductID": "string", "ParentCategory": "string"},
        )
        if "ProductID" in df.columns and "ParentCategory" in df.columns:
            return dict(zip(df["ProductID"].astype(str), df["ParentCategory"].fillna("").astype(str)))
    except Exception as exc:
        logger.warning("Không lấy được catalog_features từ ClickHouse: %s", exc)
    return {}
