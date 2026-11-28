'use strict';
/**
 * Quản lý đơn hàng — trang quản trị, tab "Đơn hàng" trong Quản lý chung (27/11/2026).
 *
 * Mount dưới '/api/b2b' SAU app.use('/api/b2b', requireAdmin) trong index.js, nên mọi route ở
 * đây đã qua requireAdmin (req.adminUser có sẵn).
 *
 *   GET  /api/b2b/orders               danh sách, lọc + phân trang (services/orderAdmin.js)
 *   GET  /api/b2b/orders/:id           chi tiết: dòng hàng, giao dịch, voucher, điểm
 *   POST /api/b2b/orders/:id/shipping  CONFIRMED -> SHIPPING (orderLifecycle.markShipping)
 *   POST /api/b2b/orders/:id/cancel    huỷ kèm lý do (orderLifecycle.cancelOrder: trả kho,
 *                                      voucher, điểm; đơn đã thu tiền -> REFUND_REQUIRED, xử lý
 *                                      hoàn tiền ở trang Đối soát)
 * "Đã giao" dùng route có sẵn POST /api/b2b/orders/:id/delivered (routes/payment.js).
 */
const express = require('express');
const { prisma } = require('../db');
const lifecycle = require('../services/payment/orderLifecycle');
const oa = require('../services/orderAdmin');

const router = express.Router();

const ORDER_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const REASON_MAX = 500;

// Lỗi nghiệp vụ từ orderLifecycle là Error thường với câu tiếng Việt; "Không tìm thấy" -> 404.
function sendLifecycleError(res, err) {
  const msg = err?.message || 'Lỗi không xác định';
  return res.status(msg.startsWith('Không tìm thấy') ? 404 : 400).json({ error: msg });
}

const LIST_SELECT = {
  id: true, date: true, customer: true, customer_id: true, province: true, total: true,
  status: true, payment_method: true, payment_status: true,
  _count: { select: { items: true } },
};

router.get('/orders', async (req, res) => {
  try {
    const parsed = oa.parseOrderListQuery(req.query);
    if (!parsed.ok) return res.status(400).json({ error: parsed.error });
    const { page, limit, where, email } = parsed;

    if (email) {
      const found = await prisma.b2CCustomer.findMany({
        where: { email: { equals: email, mode: 'insensitive' } },
        select: { id: true },
        take: 5,
      });
      if (found.length === 0) return res.json({ data: [], total: 0, page, limit });
      where.customer_id = { in: found.map((c) => c.id) };
    }

    const [total, rows] = await Promise.all([
      prisma.order.count({ where }),
      prisma.order.findMany({
        where,
        select: LIST_SELECT,
        orderBy: [{ date: 'desc' }, { id: 'desc' }],
        skip: (page - 1) * limit,
        take: limit,
      }),
    ]);
    res.json({ data: rows.map(oa.toOrderListDto), total, page, limit });
  } catch (err) {
    console.error('[admin-orders] list:', err.message);
    res.status(500).json({ error: 'Không tải được danh sách đơn hàng' });
  }
});

router.get('/orders/:id', async (req, res) => {
  const orderId = String(req.params.id);
  if (!ORDER_ID_RE.test(orderId)) return res.status(400).json({ error: 'Mã đơn không hợp lệ' });
  try {
    const order = await prisma.order.findUnique({
      where: { id: orderId },
      include: { items: { orderBy: { id: 'asc' } } },
    });
    if (!order) return res.status(404).json({ error: 'Không tìm thấy đơn hàng' });

    const [account, transactions, vouchers, loyalty] = await Promise.all([
      order.customer_id
        ? prisma.b2CCustomer.findUnique({
          where: { id: order.customer_id },
          select: { id: true, full_name: true, email: true, phone: true, is_active: true },
        })
        : null,
      prisma.paymentTransaction.findMany({
        where: { order_id: orderId },
        select: {
          id: true, provider: true, amount: true, received_at: true, match_status: true,
          confirm_reason: true, refunded_at: true, refunded_amount: true,
        },
        orderBy: { received_at: 'asc' },
      }),
      prisma.voucherUsage.findMany({
        where: { order_id: orderId },
        select: { amount: true, status: true, voucher: { select: { code: true } } },
      }),
      prisma.loyaltyTransaction.findMany({
        where: { order_id: orderId },
        select: { points: true, reason: true, status: true, created_at: true },
        orderBy: { created_at: 'asc' },
      }),
    ]);

    res.json(oa.toOrderDetailDto({ order, account, transactions, vouchers, loyalty }));
  } catch (err) {
    console.error('[admin-orders] detail:', err.message);
    res.status(500).json({ error: 'Không tải được chi tiết đơn hàng' });
  }
});

router.post('/orders/:id/shipping', async (req, res) => {
  const orderId = String(req.params.id);
  if (!ORDER_ID_RE.test(orderId)) return res.status(400).json({ error: 'Mã đơn không hợp lệ' });
  try {
    const result = await prisma.$transaction((tx) => lifecycle.markShipping(tx, orderId));
    console.log('[admin-ship-order]', JSON.stringify({ orderId, by: req.adminUser.id, ...result }));
    res.json({ success: true, order_id: orderId, ...result });
  } catch (err) {
    sendLifecycleError(res, err);
  }
});

router.post('/orders/:id/cancel', async (req, res) => {
  const orderId = String(req.params.id);
  if (!ORDER_ID_RE.test(orderId)) return res.status(400).json({ error: 'Mã đơn không hợp lệ' });
  const reason = String(req.body?.reason || '').trim();
  if (!reason) return res.status(400).json({ error: 'Vui lòng nhập lý do huỷ đơn' });
  if (reason.length > REASON_MAX) return res.status(400).json({ error: `Lý do tối đa ${REASON_MAX} ký tự` });

  try {
    const result = await prisma.$transaction((tx) =>
      lifecycle.cancelOrder(tx, orderId, { reason, cancelledBy: req.adminUser.id })
    );
    // Kho vừa được cộng lại -> báo các trang đang mở cập nhật tồn kho (như khi khách tự huỷ).
    if (result.changed) req.app?.locals?.broadcastStockUpdate?.();
    console.log('[admin-cancel-order]', JSON.stringify({ orderId, by: req.adminUser.id, reason, ...result }));
    res.json({
      success: true,
      order_id: orderId,
      changed: result.changed,
      refund_required: !!result.refundRequired,
      message: !result.changed
        ? 'Đơn đã được huỷ trước đó'
        : result.refundRequired
          ? 'Đã huỷ đơn. Đơn đã thanh toán — xử lý hoàn tiền ở trang Đối soát.'
          : 'Đã huỷ đơn hàng.',
    });
  } catch (err) {
    sendLifecycleError(res, err);
  }
});

module.exports = router;
