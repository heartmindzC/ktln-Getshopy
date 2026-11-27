"""Dự đoán xác suất sản phẩm sẽ được mua trong W ngày tới (Phương án A).

Hỗ trợ hai biến thể xác suất mua lặp lại theo thời gian:
  1. ``poisson_gamma`` (A1 — Modified Poisson–Gamma, Empirical Bayes):
     Tốc độ mua lại tiềm ẩn λ_ui ~ Gamma(α_c, β_c) theo danh mục; cập nhật hậu
     nghiệm từ số lần mua lại x = k − 1 trong khoảng quan sát T_obs:
         P(N_W >= 1 | x, T_obs) = 1 − ((β_c + T_obs) / (β_c + T_obs + W))^(α_c + x)

  2. ``ipt_hazard`` (A2 — Log-Normal Inter-Purchase Time Hazard + Repeat Propensity):
     Mô hình hoá khoảng cách giữa hai lần mua Δt ~ LogNormal(μ_ui, σ_ui²) có co rút
     Empirical Bayes về danh mục, kết hợp xác suất còn quay lại:
         P(u, i, W) = p_repeat(u, i) · (F(t_0 + W) − F(t_0)) / (1 − F(t_0))

Cấu trúc lưu trữ dùng mảng NumPy phẳng kiểu CSR (không lồng dict theo cặp) để
chứa hàng triệu cặp (khách, món) với lượng RAM nhỏ và suy luận < 1 ms/khách.

Tài liệu:
  Bhagat, R., Muralidharan, S., Lobzhanidze, A., & Vishwanath, S. (2018).
    Buy It Again: Modeling Repeat Purchase Recommendations. KDD '18, 62–70.
  Fader, P. S., Hardie, B. G. S., & Lee, K. L. (2005). "Counting Your Customers"
    the Easy Way: An Alternative to the Pareto/NBD Model. Marketing Science, 24(2).
  Wang, J., & Zhang, Y. (2013). Opportunity Model for E-Commerce Recommendation:
    Right Product; Right Time. SIGIR '13, 303–312.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.special import ndtr

NEXT_WEEK_MODEL_TYPES = ("poisson_gamma", "ipt_hazard")
REFERENCE_MODES = ("now", "max_date")
REQUIRED_COLUMNS = ("CustomerID", "ProductID", "DaysSince")
ARTIFACT_FORMAT = 1


def _category_moments(
    cat_idx: np.ndarray,
    values: np.ndarray,
    n_cats: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Tính (count, mean, var) theo từng nhóm danh mục bằng bincount thuần NumPy."""
    counts = np.bincount(cat_idx, minlength=n_cats).astype(np.int64)
    sums = np.bincount(cat_idx, weights=values, minlength=n_cats)
    sum_sq = np.bincount(cat_idx, weights=values * values, minlength=n_cats)
    means = np.zeros(n_cats, dtype=np.float64)
    variances = np.zeros(n_cats, dtype=np.float64)
    pos = counts > 0
    means[pos] = sums[pos] / counts[pos]
    variances[pos] = np.maximum(sum_sq[pos] / counts[pos] - means[pos] ** 2, 0.0)
    return counts, means, variances


class NextWeekPredictor:
    """Mô hình dự đoán xác suất khách mua lại từng sản phẩm trong cửa sổ W ngày tới."""

    def __init__(
        self,
        model_type: str = "poisson_gamma",
        reference_mode: str = "now",
        prior_m0: float = 2.0,
        prior_v0: float = 2.0,
        repeat_prior_strength: float = 2.0,
        min_sigma: float = 0.25,
    ) -> None:
        if model_type not in NEXT_WEEK_MODEL_TYPES:
            raise ValueError(
                f"model_type phải thuộc {NEXT_WEEK_MODEL_TYPES}, nhận: {model_type!r}"
            )
        if reference_mode not in REFERENCE_MODES:
            raise ValueError(
                f"reference_mode phải thuộc {REFERENCE_MODES}, nhận: {reference_mode!r}"
            )
        self.model_type = model_type
        self.reference_mode = reference_mode
        self.prior_m0 = float(prior_m0)
        self.prior_v0 = float(prior_v0)
        self.repeat_prior_strength = float(repeat_prior_strength)
        self.min_sigma = float(min_sigma)
        self.reference_shift_days: float = 0.0

        self._user_map: dict[str, int] = {}
        self._user_indptr: np.ndarray = np.zeros(1, dtype=np.int64)
        self._item_vocab: np.ndarray = np.empty(0, dtype=object)
        self._pair_item_idx: np.ndarray = np.empty(0, dtype=np.int32)
        self._counts: np.ndarray = np.empty(0, dtype=np.int32)
        self._t_obs: np.ndarray = np.empty(0, dtype=np.float32)
        self._t_last: np.ndarray = np.empty(0, dtype=np.float32)
        self._sum_log_ipt: np.ndarray = np.empty(0, dtype=np.float32)
        self._sse_log_ipt: np.ndarray = np.empty(0, dtype=np.float32)
        self._cat_idx: np.ndarray = np.empty(0, dtype=np.int16)

        self._default_cat_idx: int = 0
        self._item_cat_idx: dict[str, int] = {}
        self._alpha: np.ndarray = np.array([0.5], dtype=np.float64)
        self._beta: np.ndarray = np.array([60.0], dtype=np.float64)
        self._mu: np.ndarray = np.array([math.log(30.0)], dtype=np.float64)
        self._var: np.ndarray = np.array([0.8 ** 2], dtype=np.float64)
        self._rep_a: np.ndarray = np.array([0.5], dtype=np.float64)
        self._rep_b: np.ndarray = np.array([1.5], dtype=np.float64)

    def fit(
        self,
        events: pd.DataFrame,
        product_categories: dict[str, str] | None = None,
    ) -> "NextWeekPredictor":
        """Huấn luyện từ lịch sử mua mức ĐƠN: CustomerID, ProductID, DaysSince [, ParentCategory]."""
        if events is None:
            raise ValueError("events không được None.")
        missing = [c for c in REQUIRED_COLUMNS if c not in events.columns]
        if missing:
            raise ValueError(f"Lịch sử mua thiếu cột: {missing}")

        df = events.dropna(subset=["CustomerID", "ProductID"]).copy()
        if df.empty:
            self.reference_shift_days = 0.0
            self._user_map = {}
            self._user_indptr = np.zeros(1, dtype=np.int64)
            self._item_vocab = np.empty(0, dtype=object)
            self._pair_item_idx = np.empty(0, dtype=np.int32)
            self._counts = np.empty(0, dtype=np.int32)
            self._t_obs = np.empty(0, dtype=np.float32)
            self._t_last = np.empty(0, dtype=np.float32)
            self._sum_log_ipt = np.empty(0, dtype=np.float32)
            self._sse_log_ipt = np.empty(0, dtype=np.float32)
            self._cat_idx = np.empty(0, dtype=np.int16)
            return self

        cust_str = df["CustomerID"].astype(str)
        prod_str = df["ProductID"].astype(str)
        days = pd.to_numeric(df["DaysSince"], errors="coerce").fillna(0.0).clip(lower=0.0).to_numpy(dtype=np.float64)

        if self.reference_mode == "max_date":
            self.reference_shift_days = float(days.min())
            days = np.maximum(days - self.reference_shift_days, 0.0)
        else:
            self.reference_shift_days = 0.0

        if "ParentCategory" in df.columns:
            cats = df["ParentCategory"].fillna("").replace(r"\\N", "", regex=False).astype(str)
        elif product_categories:
            cats = prod_str.map(product_categories).fillna("").astype(str)
        else:
            cats = pd.Series("", index=df.index, dtype="object")

        u_codes, u_uniques = pd.factorize(cust_str, sort=True)
        i_codes, i_uniques = pd.factorize(prod_str, sort=True)
        cat_codes, cat_uniques = pd.factorize(cats, sort=True)

        n_cats = len(cat_uniques) + 1
        self._default_cat_idx = n_cats - 1

        # Bảng ánh xạ nhanh ProductID -> cat_idx cho dự đoán realtime sản phẩm mới mua
        cat_map = {str(name): idx for idx, name in enumerate(cat_uniques)}
        item_cat_idx: dict[str, int] = {}
        if product_categories:
            for pid, cname in product_categories.items():
                item_cat_idx[str(pid)] = cat_map.get(str(cname), self._default_cat_idx)
        for pid, ccode in zip(i_uniques, cat_codes[np.unique(i_codes, return_index=True)[1]]):
            if str(pid) not in item_cat_idx:
                item_cat_idx[str(pid)] = int(ccode)
        self._item_cat_idx = item_cat_idx

        # Sắp xếp theo (CustomerID, ProductID, DaysSince giảm dần = cổ nhất -> mới nhất)
        order = np.lexsort((-days, i_codes, u_codes))
        u_s = u_codes[order]
        i_s = i_codes[order]
        d_s = days[order]
        c_s = cat_codes[order]

        n_rows = len(u_s)
        same_pair = (u_s[1:] == u_s[:-1]) & (i_s[1:] == i_s[:-1])
        is_start = np.empty(n_rows, dtype=bool)
        is_start[0] = True
        is_start[1:] = ~same_pair

        starts = np.flatnonzero(is_start)
        ends = np.empty_like(starts)
        ends[:-1] = starts[1:]
        ends[-1] = n_rows
        n_pairs = len(starts)

        pair_u = u_s[starts]
        pair_item_idx = i_s[starts].astype(np.int32)
        pair_cat_idx = c_s[ends - 1].astype(np.int16)
        counts = (ends - starts).astype(np.int32)
        t_obs = d_s[starts].astype(np.float32)
        t_last = d_s[ends - 1].astype(np.float32)

        # Khoảng cách giữa các lần mua liên tiếp (kẹp tối thiểu 1 ngày)
        pair_id_per_row = np.cumsum(is_start) - 1
        ipt_pair_idx = pair_id_per_row[1:][same_pair]
        ipt = np.maximum(d_s[:-1][same_pair] - d_s[1:][same_pair], 1.0)
        log_ipt = np.log(ipt)

        sum_log_f64 = np.bincount(ipt_pair_idx, weights=log_ipt, minlength=n_pairs)
        sum_sq_f64 = np.bincount(ipt_pair_idx, weights=log_ipt * log_ipt, minlength=n_pairs)
        n_ipt = np.maximum(counts - 1, 0)
        mean_sq = np.zeros(n_pairs, dtype=np.float64)
        has_ipt = n_ipt > 0
        mean_sq[has_ipt] = (sum_log_f64[has_ipt] ** 2) / n_ipt[has_ipt]
        sse_log_ipt = np.maximum(sum_sq_f64 - mean_sq, 0.0).astype(np.float32)
        sum_log_ipt = sum_log_f64.astype(np.float32)

        # Ước lượng prior Empirical Bayes theo danh mục
        self._fit_priors(
            n_cats=n_cats,
            counts=counts,
            t_obs=t_obs,
            pair_cat_idx=pair_cat_idx,
            log_ipt=log_ipt,
            ipt_cat_idx=pair_cat_idx[ipt_pair_idx],
        )

        # Đóng gói dạng CSR theo khách hàng
        user_counts = np.bincount(pair_u, minlength=len(u_uniques))
        indptr = np.empty(len(u_uniques) + 1, dtype=np.int64)
        indptr[0] = 0
        np.cumsum(user_counts, out=indptr[1:])

        self._user_map = {str(uid): idx for idx, uid in enumerate(u_uniques)}
        self._user_indptr = indptr
        self._item_vocab = i_uniques.to_numpy(dtype=object)
        self._pair_item_idx = pair_item_idx
        self._counts = counts
        self._t_obs = t_obs
        self._t_last = t_last
        self._sum_log_ipt = sum_log_ipt
        self._sse_log_ipt = sse_log_ipt
        self._cat_idx = pair_cat_idx
        return self

    def _fit_priors(
        self,
        n_cats: int,
        counts: np.ndarray,
        t_obs: np.ndarray,
        pair_cat_idx: np.ndarray,
        log_ipt: np.ndarray,
        ipt_cat_idx: np.ndarray,
    ) -> None:
        # ── A1: Gamma prior (α_c, β_c) bằng Method of Moments ───────────────
        valid_a1 = t_obs >= 1.0
        g_alpha, g_beta = 0.5, 60.0
        alpha = np.full(n_cats, g_alpha, dtype=np.float64)
        beta = np.full(n_cats, g_beta, dtype=np.float64)

        if np.any(valid_a1):
            rates = (counts[valid_a1] - 1).astype(np.float64) / t_obs[valid_a1].astype(np.float64)
            g_mean = float(rates.mean())
            g_var = float(rates.var())
            if g_mean > 1e-6 and g_var > 1e-10:
                g_beta = float(np.clip(g_mean / g_var, 1.0, 3650.0))
                g_alpha = float(np.clip(g_mean * g_beta, 0.05, 50.0))
            alpha.fill(g_alpha)
            beta.fill(g_beta)

            c_cnt, c_mean, c_var = _category_moments(pair_cat_idx[valid_a1], rates, n_cats)
            ok = (c_cnt >= 20) & (c_mean > 1e-6) & (c_var > 1e-10)
            if np.any(ok):
                c_beta = np.clip(c_mean[ok] / c_var[ok], 1.0, 3650.0)
                c_alpha = np.clip(c_mean[ok] * c_beta, 0.05, 50.0)
                beta[ok] = c_beta
                alpha[ok] = c_alpha

        # ── A2: Log-Normal IPT prior (μ_c, σ_c²) & xu hướng mua lại (a_c, b_c)
        min_var = self.min_sigma ** 2
        g_mu = math.log(30.0)
        g_var_ipt = max(0.8 ** 2, min_var)
        mu = np.full(n_cats, g_mu, dtype=np.float64)
        var = np.full(n_cats, g_var_ipt, dtype=np.float64)

        if log_ipt.size > 0:
            g_mu = float(log_ipt.mean())
            g_var_ipt = float(max(float(log_ipt.var()), min_var))
            mu.fill(g_mu)
            var.fill(g_var_ipt)

            ipt_cnt, ipt_mean, ipt_var = _category_moments(ipt_cat_idx, log_ipt, n_cats)
            ok_ipt = ipt_cnt >= 20
            if np.any(ok_ipt):
                mu[ok_ipt] = ipt_mean[ok_ipt]
                var[ok_ipt] = np.maximum(ipt_var[ok_ipt], min_var)

        g_rep = float(np.clip((counts >= 2).mean(), 0.05, 0.95)) if counts.size > 0 else 0.25
        rep_p = np.full(n_cats, g_rep, dtype=np.float64)
        if counts.size > 0:
            p_cnt, p_mean, _ = _category_moments(pair_cat_idx, (counts >= 2).astype(np.float64), n_cats)
            ok_p = p_cnt >= 20
            if np.any(ok_p):
                rep_p[ok_p] = np.clip(p_mean[ok_p], 0.05, 0.95)

        self._alpha = alpha
        self._beta = beta
        self._mu = mu
        self._var = var
        self._rep_a = self.repeat_prior_strength * rep_p
        self._rep_b = self.repeat_prior_strength * (1.0 - rep_p)

    def _resolve_model_type(self, model_type: str | None) -> str:
        chosen = self.model_type if model_type is None else model_type
        if chosen not in NEXT_WEEK_MODEL_TYPES:
            raise ValueError(
                f"model_type phải thuộc {NEXT_WEEK_MODEL_TYPES}, nhận: {chosen!r}"
            )
        return chosen

    def _score_arrays(
        self,
        counts: np.ndarray,
        t_obs: np.ndarray,
        t_last: np.ndarray,
        sum_log_ipt: np.ndarray,
        sse_log_ipt: np.ndarray,
        cat_idx: np.ndarray,
        horizon_days: float,
        model_type: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Tính vector (xác suất trong W ngày tới, chu kỳ kỳ vọng) trên mảng phẳng."""
        w = float(horizon_days)
        if counts.size == 0:
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

        n = np.maximum(counts - 1, 0).astype(np.float64)
        t_obs_f = np.maximum(t_obs.astype(np.float64), 0.0)
        t_last_f = np.maximum(t_last.astype(np.float64), 0.0)

        if model_type == "poisson_gamma":
            alpha = self._alpha[cat_idx]
            beta = self._beta[cat_idx]
            rate_denom = np.maximum(beta + t_obs_f, 1e-9)
            prob = 1.0 - np.power(rate_denom / (rate_denom + w), alpha + n)
            expected_cycle = rate_denom / np.maximum(alpha + n, 1e-9)
            return np.clip(prob, 0.0, 1.0), expected_cycle

        # ipt_hazard (A2)
        m0 = self.prior_m0
        v0 = self.prior_v0
        sum_log_f = sum_log_ipt.astype(np.float64)
        sse_f = sse_log_ipt.astype(np.float64)

        mu_hat = (m0 * self._mu[cat_idx] + sum_log_f) / (m0 + n)
        sigma_sq = np.maximum((v0 * self._var[cat_idx] + sse_f) / (v0 + n), self.min_sigma ** 2)
        sigma_hat = np.sqrt(sigma_sq)
        expected_cycle = np.exp(mu_hat)

        log_t0 = np.log(np.maximum(t_last_f, 1e-9))
        f_t0 = np.where(t_last_f > 0.0, ndtr((log_t0 - mu_hat) / sigma_hat), 0.0)
        log_t1 = np.log(np.maximum(t_last_f + w, 1e-9))
        f_t1 = ndtr((log_t1 - mu_hat) / sigma_hat)

        hazard = np.clip((f_t1 - f_t0) / np.maximum(1.0 - f_t0, 1e-9), 0.0, 1.0)
        rep_a = self._rep_a[cat_idx]
        rep_b = self._rep_b[cat_idx]
        p_repeat = (rep_a + n) / (rep_a + rep_b + n)
        prob = np.clip(p_repeat * hazard, 0.0, 1.0)
        return prob, expected_cycle

    def score_all_pairs(
        self,
        horizon_days: float = 7.0,
        model_type: str | None = None,
    ) -> np.ndarray:
        """Chấm điểm toàn bộ các cặp đã lưu trong một lượt vectorized (phục vụ benchmark)."""
        chosen = self._resolve_model_type(model_type)
        probs, _ = self._score_arrays(
            self._counts,
            self._t_obs,
            self._t_last,
            self._sum_log_ipt,
            self._sse_log_ipt,
            self._cat_idx,
            horizon_days=horizon_days,
            model_type=chosen,
        )
        return probs

    def get_pair_keys(self) -> tuple[np.ndarray, np.ndarray]:
        """Trả về mảng (CustomerID, ProductID) tương ứng với thứ tự của score_all_pairs()."""
        if self._counts.size == 0:
            return np.empty(0, dtype=object), np.empty(0, dtype=object)
        user_vocab = np.empty(len(self._user_map), dtype=object)
        for uid, idx in self._user_map.items():
            user_vocab[idx] = uid
        user_counts = np.diff(self._user_indptr)
        pair_user_idx = np.repeat(np.arange(len(user_vocab), dtype=np.int64), user_counts)
        return user_vocab[pair_user_idx], self._item_vocab[self._pair_item_idx]

    @staticmethod
    def _format_predictions(
        product_ids: np.ndarray,
        probs: np.ndarray,
        cycles: np.ndarray,
        t_last: np.ndarray,
        counts: np.ndarray,
        top_k: int,
        min_prob: float,
        reason: str,
    ) -> list[dict[str, Any]]:
        if product_ids.size == 0 or top_k < 1:
            return []
        keep = probs >= float(min_prob)
        if not np.any(keep):
            return []

        idx = np.flatnonzero(keep)
        # Sắp xếp tất định: xác suất giảm dần, số lần mua giảm dần, ProductID tăng dần
        order = sorted(
            idx.tolist(),
            key=lambda i: (-float(probs[i]), -int(counts[i]), str(product_ids[i])),
        )[:top_k]

        return [
            {
                "product_id": str(product_ids[i]),
                "purchase_probability": round(float(probs[i]), 4),
                "expected_cycle_days": round(float(cycles[i]), 1) if np.isfinite(cycles[i]) else None,
                "days_since_last_purchase": int(round(float(t_last[i]))),
                "purchase_count": int(counts[i]),
                "reason": reason,
            }
            for i in order
        ]

    def predict(
        self,
        customer_id: str,
        top_k: int = 10,
        horizon_days: float = 7.0,
        min_prob: float = 0.05,
        model_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Dự đoán top-K sản phẩm khách có xác suất mua lại cao nhất trong W ngày tới."""
        if top_k < 1:
            raise ValueError("top_k must be at least 1.")
        if horizon_days <= 0:
            raise ValueError("horizon_days must be positive.")
        chosen = self._resolve_model_type(model_type)

        uidx = self._user_map.get(str(customer_id))
        if uidx is None:
            return []
        s = int(self._user_indptr[uidx])
        e = int(self._user_indptr[uidx + 1])
        if s >= e:
            return []

        probs, cycles = self._score_arrays(
            self._counts[s:e],
            self._t_obs[s:e],
            self._t_last[s:e],
            self._sum_log_ipt[s:e],
            self._sse_log_ipt[s:e],
            self._cat_idx[s:e],
            horizon_days=horizon_days,
            model_type=chosen,
        )
        return self._format_predictions(
            self._item_vocab[self._pair_item_idx[s:e]],
            probs,
            cycles,
            self._t_last[s:e],
            self._counts[s:e],
            top_k=top_k,
            min_prob=min_prob,
            reason=chosen,
        )

    def predict_realtime(
        self,
        customer_id: str,
        purchased_product_ids: Iterable[str] = (),
        top_k: int = 10,
        horizon_days: float = 7.0,
        min_prob: float = 0.05,
        model_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Dự đoán 7 ngày tới có gộp các món khách vừa mua trong ngày (DaysSince = 0)."""
        if top_k < 1:
            raise ValueError("top_k must be at least 1.")
        if horizon_days <= 0:
            raise ValueError("horizon_days must be positive.")
        chosen = self._resolve_model_type(model_type)

        fresh_ids = [p for p in dict.fromkeys(str(x).strip() for x in purchased_product_ids) if p]
        if not fresh_ids:
            return self.predict(
                customer_id=customer_id,
                top_k=top_k,
                horizon_days=horizon_days,
                min_prob=min_prob,
                model_type=chosen,
            )

        uidx = self._user_map.get(str(customer_id))
        if uidx is not None:
            s = int(self._user_indptr[uidx])
            e = int(self._user_indptr[uidx + 1])
            product_ids = list(map(str, self._item_vocab[self._pair_item_idx[s:e]]))
            counts = self._counts[s:e].astype(np.int32).tolist()
            t_obs = self._t_obs[s:e].astype(np.float64).tolist()
            t_last = self._t_last[s:e].astype(np.float64).tolist()
            sum_log = self._sum_log_ipt[s:e].astype(np.float64).tolist()
            sse_log = self._sse_log_ipt[s:e].astype(np.float64).tolist()
            cat_idx = self._cat_idx[s:e].astype(np.int16).tolist()
        else:
            product_ids, counts, t_obs, t_last, sum_log, sse_log, cat_idx = [], [], [], [], [], [], []

        pos = {pid: i for i, pid in enumerate(product_ids)}
        for pid in fresh_ids:
            idx = pos.get(pid)
            if idx is not None:
                old_n = max(counts[idx] - 1, 0)
                new_ipt = max(float(t_last[idx]), 1.0)
                log_new = math.log(new_ipt)
                old_sum = sum_log[idx]
                old_sum_sq = sse_log[idx] + ((old_sum * old_sum) / old_n if old_n > 0 else 0.0)
                new_sum = old_sum + log_new
                new_n = old_n + 1
                new_sse = max(old_sum_sq + log_new * log_new - (new_sum * new_sum) / new_n, 0.0)

                counts[idx] += 1
                t_last[idx] = 0.0
                sum_log[idx] = new_sum
                sse_log[idx] = new_sse
            else:
                pos[pid] = len(product_ids)
                product_ids.append(pid)
                counts.append(1)
                t_obs.append(0.0)
                t_last.append(0.0)
                sum_log.append(0.0)
                sse_log.append(0.0)
                cat_idx.append(self._item_cat_idx.get(pid, self._default_cat_idx))

        counts_arr = np.asarray(counts, dtype=np.int32)
        t_obs_arr = np.asarray(t_obs, dtype=np.float32)
        t_last_arr = np.asarray(t_last, dtype=np.float32)
        sum_log_arr = np.asarray(sum_log, dtype=np.float32)
        sse_log_arr = np.asarray(sse_log, dtype=np.float32)
        cat_arr = np.asarray(cat_idx, dtype=np.int16)

        probs, cycles = self._score_arrays(
            counts_arr,
            t_obs_arr,
            t_last_arr,
            sum_log_arr,
            sse_log_arr,
            cat_arr,
            horizon_days=horizon_days,
            model_type=chosen,
        )
        return self._format_predictions(
            np.asarray(product_ids, dtype=object),
            probs,
            cycles,
            t_last_arr,
            counts_arr,
            top_k=top_k,
            min_prob=min_prob,
            reason=chosen,
        )

    def get_purchase_history(
        self,
        customer_id: str,
        limit: int = 50,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Trả về (tổng số món đã mua, danh sách món mua gần đây nhất: product_id, days_since_last_purchase, purchase_count)."""
        uidx = self._user_map.get(str(customer_id))
        if uidx is None:
            return 0, []
        s = int(self._user_indptr[uidx])
        e = int(self._user_indptr[uidx + 1])
        total = e - s
        if total <= 0:
            return 0, []

        pids = self._item_vocab[self._pair_item_idx[s:e]]
        t_lasts = self._t_last[s:e]
        counts = self._counts[s:e]

        # Sắp xếp: ngày mua gần đây nhất trước (t_last nhỏ nhất trước), nếu hòa thì số lần mua nhiều hơn
        order = sorted(range(total), key=lambda i: (float(t_lasts[i]), -int(counts[i]), str(pids[i])))[:limit]
        items = [
            {
                "product_id": str(pids[i]),
                "days_since_last_purchase": int(round(float(t_lasts[i]))),
                "purchase_count": int(counts[i]),
            }
            for i in order
        ]
        return total, items

    def customers(self) -> set[str]:
        return set(self._user_map)

    def summary(self) -> dict[str, int | str]:
        return {
            "next_week_customers": len(self._user_map),
            "next_week_pairs": int(self._counts.size),
            "next_week_categories": int(len(self._alpha)),
            "next_week_model_type": self.model_type,
        }

    def save(self, path: Path) -> Path:
        """Ghi nguyên tử qua file tạm rồi os.replace như HybridRecommender."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        joblib.dump({"format_version": ARTIFACT_FORMAT, "predictor": self}, tmp, compress=3)
        os.replace(tmp, path)
        return path

    @staticmethod
    def load(path: Path) -> "NextWeekPredictor":
        payload = joblib.load(Path(path))
        if payload.get("format_version") != ARTIFACT_FORMAT:
            raise ValueError(f"Unsupported next_week artifact format: {payload.get('format_version')}")
        return payload["predictor"]
