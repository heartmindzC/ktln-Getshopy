'use strict';
/**
 * ============================================================
 * RECOMMENDATION ROUTES — AI Product Recommendations
 * routes/recommendation.js
 * ============================================================
 *
 * Thin controller — chỉ nhận request, gọi RecommendationService, trả response.
 *
 * Endpoints:
 *   GET /api/b2c/recommendations          — Gợi ý sản phẩm cho khách hàng
 *   GET /api/b2c/recommendations/next-week — "Có thể bạn cần": món sắp cần mua lại (7 ngày)
 *   GET /api/b2c/similar/:productId       — Sản phẩm tương tự (specs-aware)
 */

const express = require('express');
const router = express.Router();
const RecommendationService = require('../services/RecommendationService');
const { optionalAuthB2C } = require('../middleware/authB2C');

// ─────────────────────────────────────────────────────────────────────────────
// GET /api/b2c/recommendations
//
// DANH TÍNH LẤY TỪ TOKEN, KHÔNG TỪ QUERY STRING.
//
// Bản trước đọc `customerId` từ `req.query`, trong khi client chỉ gửi `email`
// (services/api.js) và `getRecommendations()` KHÔNG hề dùng tới email. Hệ quả:
// `customerId` luôn undefined, nên nhánh gọi container AI-Rec
// (`if (results.length < 8 && customerId && AI_REC_URL)`) KHÔNG BAO GIỜ chạy.
// Trang chủ rơi thẳng xuống fallback rule-based mà không có lỗi nào báo ra —
// API vẫn trả 200 kèm đủ 8 sản phẩm, nhìn từ ngoài y hệt như gợi ý AI đang chạy.
//
// Dùng optionalAuthB2C chứ không authB2C: đây là endpoint công khai, khách vãng
// lai phải xem được gợi ý. Bắt buộc đăng nhập thì khách chưa có token nhận 401,
// mà `request()` phía client xử lý 401 bằng localStorage.clear() +
// redirect '/' — tức là trang chủ tự tải lại vô hạn.
//
// Có token hợp lệ -> req.b2cUser.id -> đi đường Collaborative Filtering.
// Không có -> khách vãng lai, đi đường rule-based như cũ.
// ─────────────────────────────────────────────────────────────────────────────
router.get('/b2c/recommendations', optionalAuthB2C, async (req, res) => {
  try {
    const { categoryId, brandId, sessionId } = req.query;
    const result = await RecommendationService.getRecommendations(
      null,
      {
        categoryId: categoryId || undefined,
        brandId: brandId || undefined,
        sessionId: sessionId || undefined,
        // Chỉ tin token. Nhận id do client khai thì ai cũng xem được gợi ý
        // của người khác chỉ bằng cách đổi một tham số trên URL.
        customerId: req.b2cUser ? req.b2cUser.id : undefined,
      }
    );
    res.json(result);
  } catch (err) {
    console.error('[Recommendation Error]', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// GET /api/b2c/recommendations/next-week — "Có thể bạn cần" (25/11/2026)
//
// Món khách có thể sắp cần MUA LẠI trong 7 ngày tới, theo chu kỳ mua lặp lại (ai-rec
// /api/v1/predict/next-week, xem RecommendationService.getNextWeekProducts).
//
// Cùng nguyên tắc với /b2c/recommendations: danh tính CHỈ lấy từ token (optionalAuthB2C) —
// nhận id trên URL thì đổi tham số là xem được lịch sử mua của người khác. Khách vãng lai
// không có lịch sử mua -> [] (không 401: request() phía client xử lý 401 bằng xoá phiên +
// về trang chủ). [] thì trang chủ ẩn section, không thay bằng hàng bán chạy (sai ý nghĩa).
// ─────────────────────────────────────────────────────────────────────────────
router.get('/b2c/recommendations/next-week', optionalAuthB2C, async (req, res) => {
  try {
    if (!req.b2cUser) return res.json([]);
    const result = await RecommendationService.getNextWeekProducts(req.b2cUser.id, { topK: 8 });
    res.json(result);
  } catch (err) {
    console.error('[NextWeek Recommendation Error]', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// GET /api/b2c/similar/:productId — Sản phẩm tương tự (specs similarity)
// ─────────────────────────────────────────────────────────────────────────────
router.get('/b2c/similar/:productId', async (req, res) => {
  try {
    const { productId } = req.params;
    if (!productId || isNaN(productId)) {
      return res.status(400).json({ error: 'productId phải là số hợp lệ' });
    }
    const result = await RecommendationService.getRelatedProducts(productId);
    res.json(result);
  } catch (err) {
    console.error('[Similar Error]', err.message);
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
