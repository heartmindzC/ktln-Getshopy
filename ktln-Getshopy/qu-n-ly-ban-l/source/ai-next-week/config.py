"""Centralized configuration for Next-Week Prediction Service."""

import os
from pathlib import Path

# Thư mục gốc của service
PROJECT_ROOT = Path(__file__).resolve().parent

# Thư mục dữ liệu và output
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
OUTPUT_DIR = PROJECT_ROOT / "output"
NEXT_WEEK_MODEL_PATH = OUTPUT_DIR / "next_week" / "predictor.joblib"

# Tham số mặc định
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "10"))
NEXT_WEEK_DEFAULT_HORIZON_DAYS = int(os.getenv("NEXT_WEEK_DEFAULT_HORIZON_DAYS", "7"))
NEXT_WEEK_DEFAULT_MIN_PROB = float(os.getenv("NEXT_WEEK_DEFAULT_MIN_PROB", "0.05"))
NEXT_WEEK_MAX_RECENT_PURCHASES = int(os.getenv("NEXT_WEEK_MAX_RECENT_PURCHASES", "200"))
NEXT_WEEK_MODEL_TYPE = os.getenv("NEXT_WEEK_MODEL_TYPE", "poisson_gamma")
NEXT_WEEK_REFERENCE_MODE = os.getenv("NEXT_WEEK_REFERENCE_MODE", "now")

# ClickHouse connection
CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "").rstrip("/")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "ai_rec")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_TIMEOUT_SECONDS = float(os.getenv("CLICKHOUSE_TIMEOUT_SECONDS", "60.0"))

PURCHASE_EVENTS_TABLE = os.getenv("PURCHASE_EVENTS_TABLE", "serving.purchase_events_for_AI_rec")
PURCHASE_EVENTS_QUERY = (
    f"SELECT pe.CustomerID, pe.ProductID, "
    f"dateDiff('day', pe.OrderedAt, now()) AS DaysSince, "
    f"cf.ParentCategory "
    f"FROM {PURCHASE_EVENTS_TABLE} pe "
    f"LEFT JOIN serving.catalog_features cf ON cf.ProductID = pe.ProductID "
    f"FORMAT TabSeparatedWithNames"
)

CATALOG_FEATURES_QUERY = (
    "SELECT ProductID, ParentCategory "
    "FROM serving.catalog_features "
    "FORMAT TabSeparatedWithNames"
)

# Lịch trình huấn luyện lại định kỳ
TRAIN_DAILY_AT = os.getenv("TRAIN_DAILY_AT", "22:00")
TRAIN_TIMEZONE = os.getenv("TRAIN_TIMEZONE", "Asia/Ho_Chi_Minh")
TRAIN_INTERVAL_SECONDS = int(os.getenv("TRAIN_INTERVAL_SECONDS", "300"))
