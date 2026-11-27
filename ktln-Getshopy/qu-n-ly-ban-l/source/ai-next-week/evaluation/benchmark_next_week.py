"""Benchmark học thuật cho bài toán dự đoán sản phẩm mua lại trong 7 ngày tới.

Chia dữ liệu theo thời gian (Temporal Split — không rò rỉ tương lai):
  - Validation window: cut = max_date - 14 ngày -> dự đoán mua lại trong (cut, cut + 7]
  - Test window:       cut = max_date - 7 ngày  -> dự đoán mua lại trong (cut, cut + 7]

Đối chứng 3 mô hình trên toàn bộ các cặp (CustomerID, ProductID) đã xuất hiện ở tập train:
  1. Baseline: RepeatModel(half_life=37 ngày) — điểm thô cho AUC/PR-AUC/ranking, 1 - exp(-score) cho Brier/LogLoss
  2. A1: NextWeekPredictor(model_type="poisson_gamma")
  3. A2: NextWeekPredictor(model_type="ipt_hazard")
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

from models.next_week import NextWeekPredictor

DATA_DIR = Path(__file__).resolve().parent / "data"
RESULTS_PATH = Path(__file__).resolve().parent / "results" / "benchmark_next_week.md"
REPEAT_HALF_LIFE_DAYS = 37.0
HORIZON_DAYS = 7.0


def load_order_events() -> tuple[pd.DataFrame, dict[str, str]]:
    """Đọc order_lines.csv và gộp về mức đơn hàng (CustomerID, ProductID, OrderID)."""
    orders_path = DATA_DIR / "order_lines.csv"
    cats_path = DATA_DIR / "catalog_features.csv"

    raw = pd.read_csv(
        orders_path,
        usecols=["CustomerID", "ProductID", "OrderID", "OrderDate"],
        dtype={"CustomerID": "string", "ProductID": "string", "OrderID": "string"},
    )
    raw["OrderDate"] = pd.to_datetime(raw["OrderDate"], errors="coerce")
    raw = raw.dropna(subset=["CustomerID", "ProductID", "OrderID", "OrderDate"])

    events = raw.groupby(["CustomerID", "ProductID", "OrderID"], as_index=False)["OrderDate"].min()

    prod_cats: dict[str, str] = {}
    if cats_path.exists():
        cf = pd.read_csv(
            cats_path,
            usecols=["ProductID", "ParentCategory"],
            dtype={"ProductID": "string", "ParentCategory": "string"},
        ).dropna()
        prod_cats = dict(zip(cf["ProductID"].astype(str), cf["ParentCategory"].astype(str)))
        events["ParentCategory"] = events["ProductID"].map(prod_cats).fillna("")
    else:
        events["ParentCategory"] = ""
    return events, prod_cats


def _repeat_baseline_scores(
    train_ev: pd.DataFrame,
    u_keys: np.ndarray,
    i_keys: np.ndarray,
    half_life: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Tính điểm RepeatModel vectorized trên đúng thứ tự (u_keys, i_keys)."""
    w = np.power(0.5, train_ev["DaysSince"].to_numpy(dtype=np.float64) / half_life)
    grouped = (
        pd.DataFrame({"CustomerID": train_ev["CustomerID"], "ProductID": train_ev["ProductID"], "w": w})
        .groupby(["CustomerID", "ProductID"], sort=False)["w"]
        .sum()
    )
    idx = pd.MultiIndex.from_arrays([u_keys, i_keys])
    raw_scores = grouped.reindex(idx, fill_value=0.0).to_numpy(dtype=np.float64)
    # Liên kết đơn điệu 1 - exp(-score) về (0, 1) để đo Brier/LogLoss
    prob_like = 1.0 - np.exp(-raw_scores)
    return raw_scores, prob_like


def _topk_metrics(
    predictor: NextWeekPredictor,
    scores: np.ndarray,
    y_true: np.ndarray,
    target_user_set: set[str],
    top_k: int = 10,
) -> tuple[float, float, float]:
    """Tính Precision@K, Recall@K, HitRate@K trên nhóm khách có mua lại trong cửa sổ 7 ngày."""
    indptr = predictor._user_indptr
    umap = predictor._user_map
    precisions: list[float] = []
    recalls: list[float] = []
    hits: list[float] = []

    for uid in target_user_set:
        uidx = umap.get(uid)
        if uidx is None:
            continue
        s, e = int(indptr[uidx]), int(indptr[uidx + 1])
        if s >= e:
            continue
        u_y = y_true[s:e]
        total_pos = int(u_y.sum())
        if total_pos == 0:
            continue
        u_sc = scores[s:e]
        if len(u_sc) <= top_k:
            chosen = np.argsort(-u_sc, kind="stable")
        else:
            part = np.argpartition(-u_sc, top_k - 1)[:top_k]
            chosen = part[np.argsort(-u_sc[part], kind="stable")]
        tp = int(u_y[chosen].sum())
        precisions.append(tp / top_k)
        recalls.append(tp / total_pos)
        hits.append(1.0 if tp > 0 else 0.0)

    if not recalls:
        return 0.0, 0.0, 0.0
    return float(np.mean(precisions)), float(np.mean(recalls)), float(np.mean(hits))


def evaluate_split(
    events: pd.DataFrame,
    prod_cats: dict[str, str],
    cut: pd.Timestamp,
    name: str,
) -> dict[str, object]:
    """Đánh giá trên một mốc cắt thời gian (train <= cut, target in (cut, cut + 7d])."""
    window_end = cut + pd.Timedelta(days=int(HORIZON_DAYS))
    train_ev = events[events["OrderDate"] <= cut].copy()
    target_ev = events[(events["OrderDate"] > cut) & (events["OrderDate"] <= window_end)]

    cut_norm = cut.normalize()
    train_ev["DaysSince"] = np.maximum(
        (cut_norm - train_ev["OrderDate"].dt.normalize()).dt.days.to_numpy(dtype=np.int32),
        0,
    )

    t0 = time.perf_counter()
    predictor = NextWeekPredictor(model_type="poisson_gamma", reference_mode="now").fit(
        train_ev, product_categories=prod_cats
    )
    fit_sec = time.perf_counter() - t0

    u_keys, i_keys = predictor.get_pair_keys()
    target_pairs_df = target_ev[["CustomerID", "ProductID"]].drop_duplicates()
    target_idx = pd.MultiIndex.from_frame(target_pairs_df)
    pair_idx = pd.MultiIndex.from_arrays([u_keys, i_keys])
    y_true = pair_idx.isin(target_idx).astype(np.int8)

    repeat_users = set(u_keys[y_true == 1])

    p_a1 = predictor.score_all_pairs(horizon_days=HORIZON_DAYS, model_type="poisson_gamma")
    p_a2 = predictor.score_all_pairs(horizon_days=HORIZON_DAYS, model_type="ipt_hazard")
    b_raw, b_prob = _repeat_baseline_scores(train_ev, u_keys, i_keys, REPEAT_HALF_LIFE_DAYS)

    models = [
        ("RepeatBaseline (hl=37d)", b_raw, b_prob),
        ("A1: Poisson-Gamma", p_a1, p_a1),
        ("A2: IPT LogNormal Hazard", p_a2, p_a2),
    ]

    rows: list[dict[str, float | str]] = []
    for label, rank_sc, prob_sc in models:
        prob_clip = np.clip(prob_sc, 1e-6, 1.0 - 1e-6)
        roc = float(roc_auc_score(y_true, rank_sc))
        pr = float(average_precision_score(y_true, rank_sc))
        brier = float(brier_score_loss(y_true, prob_sc))
        ll = float(log_loss(y_true, prob_clip))
        prec10, rec10, hit10 = _topk_metrics(predictor, rank_sc, y_true, repeat_users, top_k=10)
        rows.append(
            {
                "model": label,
                "roc_auc": roc,
                "pr_auc": pr,
                "brier": brier,
                "log_loss": ll,
                "precision_at_10": prec10,
                "recall_at_10": rec10,
                "hit_rate_at_10": hit10,
            }
        )

    return {
        "name": name,
        "cut": str(cut),
        "window_end": str(window_end),
        "n_train_events": int(len(train_ev)),
        "n_pairs": int(len(y_true)),
        "n_positives": int(y_true.sum()),
        "positive_rate": float(y_true.mean()),
        "n_repeat_users": int(len(repeat_users)),
        "fit_sec": fit_sec,
        "rows": rows,
    }


def main() -> None:
    t_start = time.perf_counter()
    events, prod_cats = load_order_events()
    max_date = events["OrderDate"].max()
    cut_val = max_date - pd.Timedelta(days=14)
    cut_test = max_date - pd.Timedelta(days=7)

    val_res = evaluate_split(events, prod_cats, cut_val, "Validation (cut = max - 14d)")
    test_res = evaluate_split(events, prod_cats, cut_test, "Test (cut = max - 7d)")

    # Chọn mô hình thắng cuộc trên Validation theo PR-AUC (ưu tiên cao) và Brier Score (thấp)
    val_candidates = [r for r in val_res["rows"] if not str(r["model"]).startswith("RepeatBaseline")]
    winner_row = max(val_candidates, key=lambda r: (round(float(r["pr_auc"]), 6), -float(r["brier"])))
    winner_key = "poisson_gamma" if "Poisson-Gamma" in str(winner_row["model"]) else "ipt_hazard"

    lines = [
        "# Benchmark: Dự đoán sản phẩm mua lại trong 7 ngày tới (Phương án A)",
        "",
        f"> **Ngày chạy:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"> **Dữ liệu:** `evaluation/data/order_lines.csv` ({len(events):,} sự kiện cấp đơn hàng; {events['CustomerID'].nunique():,} khách; {events['ProductID'].nunique():,} sản phẩm)  ",
        f"> **Cửa sổ dự đoán:** $W = {int(HORIZON_DAYS)}$ ngày (chia Temporal Split, không rò rỉ tương lai)",
        "",
    ]

    for res in (val_res, test_res):
        lines.extend(
            [
                f"## {res['name']}",
                "",
                f"- **Mốc cắt:** `{res['cut']}` $\\to$ `{res['window_end']}`",
                f"- **Cặp ứng viên (đã mua trước cut):** {res['n_pairs']:,} | **Dương tính (mua lại trong 7 ngày):** {res['n_positives']:,} ({res['positive_rate']*100:.2f}%) | **Khách có mua lại:** {res['n_repeat_users']:,}",
                f"- **Thời gian fit:** {res['fit_sec']:.2f}s",
                "",
                "| Mô hình | ROC-AUC ↑ | PR-AUC ↑ | Brier ↓ | LogLoss ↓ | Precision@10 ↑ | Recall@10 ↑ | HitRate@10 ↑ |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for r in res["rows"]:
            lines.append(
                f"| {r['model']} | {r['roc_auc']:.4f} | {r['pr_auc']:.4f} | {r['brier']:.5f} | "
                f"{r['log_loss']:.4f} | {r['precision_at_10']:.4f} | {r['recall_at_10']:.4f} | {r['hit_rate_at_10']:.4f} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Kết luận chọn mô hình mặc định",
            "",
            f"- **Mô hình thắng trên Validation:** `{winner_row['model']}` (`NEXT_WEEK_MODEL_TYPE = \"{winner_key}\"`)",
            f"- Tổng thời gian chạy benchmark: {time.perf_counter() - t_start:.1f}s",
        ]
    )

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = "\n".join(lines) + "\n"
    RESULTS_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"WINNER_KEY={winner_key}")


if __name__ == "__main__":
    main()
