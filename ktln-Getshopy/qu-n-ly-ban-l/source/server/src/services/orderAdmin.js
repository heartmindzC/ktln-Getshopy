'use strict';
/**
 * Quản lý đơn hàng ở trang quản trị (27/11/2026) — phần thuần, không I/O, để kiểm thử
 * bằng `node --test tests/order-admin.test.js` không cần Postgres.
 *
 *   parseOrderListQuery(query)  kiểm tham số lọc của GET /api/b2b/orders, dựng `where` Prisma
 *   toOrderListDto(order)       một dòng của bảng danh sách
 *   toOrderDetailDto(...)       ngăn chi tiết: đơn + dòng hàng + giao dịch + voucher + điểm
 *   allowedActions(order)       thao tác quản trị viên làm được trên đơn ở trạng thái hiện tại
 *
 * Bảng Order có ~3 triệu dòng. Mọi bộ lọc đều đi qua cột có chỉ mục (status, date,
 * customer_id, khoá chính id); không tìm theo tên / SĐT trong cột Json customer vì sẽ quét cả
 * bảng. Tìm khách theo email thì route đổi email -> customer_id trước (bảng khách ~40 nghìn dòng).
 */

// Order.status — schema.prisma. COMPLETED: giá trị cũ còn trong dữ liệu (ghi chú ở
// KpiTodayService.js, đo 16/11/2026); giao diện khách coi như "đã giao".
const ORDER_STATUSES = ['PENDING_PAYMENT', 'CONFIRMED', 'SHIPPING', 'DELIVERED', 'COMPLETED', 'CANCELLED'];
const PAYMENT_STATUSES = ['UNPAID', 'PENDING', 'PAID', 'EXPIRED', 'FAILED', 'CANCELLED', 'REFUND_REQUIRED', 'REFUNDED'];
const PAYMENT_METHODS = ['COD', 'BANK_TRANSFER'];

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
// Giờ nghiệp vụ Asia/Ho_Chi_Minh: UTC+7 cố định, không có giờ mùa hè.
const BIZ_OFFSET = '+07:00';
const MAX_LIMIT = 100;

/** 'YYYY-MM-DD' theo giờ Việt Nam -> Date lúc 00:00 ngày đó (giờ VN), sai định dạng -> null. */
function bizDayStart(s) {
  if (typeof s !== 'string' || !DATE_RE.test(s)) return null;
  const d = new Date(`${s}T00:00:00${BIZ_OFFSET}`);
  return Number.isNaN(d.getTime()) ? null : d;
}

const isAll = (v) => v === undefined || v === null || v === '' || v === 'all';

/**
 * Kiểm tham số lọc. Trả `{ ok, error }` hoặc `{ ok, page, limit, where, email }`.
 * `email` khác null nghĩa là route phải đổi email -> customer_id rồi gộp vào `where`.
 *
 * Ô tìm `q`:
 *   - có '@'         -> email khách (so không phân biệt hoa thường)
 *   - toàn chữ số    -> mã khách (customer_id)
 *   - còn lại        -> mã đơn, khớp đúng (khoá chính)
 */
function parseOrderListQuery(query = {}) {
  const page = Math.max(1, Number.parseInt(query.page, 10) || 1);
  const limit = Math.min(MAX_LIMIT, Math.max(1, Number.parseInt(query.limit, 10) || 20));
  const where = {};

  const pick = (name, value, allowed) => {
    if (isAll(value)) return true;
    if (!allowed.includes(value)) return false;
    where[name] = value;
    return true;
  };
  if (!pick('status', query.status, ORDER_STATUSES)) return { ok: false, error: 'Trạng thái đơn không hợp lệ' };
  if (!pick('payment_status', query.payment_status, PAYMENT_STATUSES)) return { ok: false, error: 'Trạng thái thanh toán không hợp lệ' };
  if (!pick('payment_method', query.payment_method, PAYMENT_METHODS)) return { ok: false, error: 'Phương thức thanh toán không hợp lệ' };

  const date = {};
  if (!isAll(query.date_from)) {
    const from = bizDayStart(query.date_from);
    if (!from) return { ok: false, error: 'Ngày bắt đầu phải có dạng YYYY-MM-DD' };
    date.gte = from;
  }
  if (!isAll(query.date_to)) {
    const to = bizDayStart(query.date_to);
    if (!to) return { ok: false, error: 'Ngày kết thúc phải có dạng YYYY-MM-DD' };
    date.lt = new Date(to.getTime() + 86400000); // hết ngày date_to (giờ VN)
  }
  if (date.gte && date.lt && date.gte >= date.lt) return { ok: false, error: 'Ngày bắt đầu phải trước ngày kết thúc' };
  if (date.gte || date.lt) where.date = date;

  let email = null;
  const q = typeof query.q === 'string' ? query.q.trim() : '';
  if (q) {
    if (q.length > 200) return { ok: false, error: 'Từ khoá quá dài' };
    if (q.includes('@')) email = q.toLowerCase();
    else if (/^\d{1,18}$/.test(q)) where.customer_id = BigInt(q);
    else where.id = q;
  }

  return { ok: true, page, limit, where, email };
}

const num = (v) => (v === null || v === undefined ? null : Number(v));

/**
 * Người nhận từ bản chụp Json lúc đặt hàng. Khoá theo validateCustomerInfo (utils/validators.js):
 * full_name, phone, email, address, ward, district, province. Bản ghi cũ / dữ liệu sinh có thể
 * dùng `name` nên đọc cả hai.
 */
function recipientOf(snapshot) {
  const c = snapshot && typeof snapshot === 'object' ? snapshot : {};
  const parts = [c.address, c.ward, c.district, c.province]
    .map((p) => (typeof p === 'string' ? p.trim() : ''))
    .filter(Boolean);
  return {
    name: c.full_name || c.name || null,
    phone: c.phone || null,
    email: c.email || null,
    address: parts.length ? parts.join(', ') : null,
  };
}

/** Thao tác quản trị hợp lệ theo trạng thái — server vẫn kiểm lại trong orderLifecycle. */
function allowedActions(order) {
  const s = order?.status;
  return {
    ship: s === 'CONFIRMED',
    deliver: s === 'CONFIRMED' || s === 'SHIPPING',
    cancel: s === 'PENDING_PAYMENT' || s === 'CONFIRMED' || s === 'SHIPPING',
  };
}

function toOrderListDto(o) {
  const r = recipientOf(o.customer);
  return {
    id: o.id,
    date: o.date,
    customer_id: num(o.customer_id),
    recipient_name: r.name,
    recipient_phone: r.phone,
    province: o.province || null,
    item_count: o._count?.items ?? null,
    total: num(o.total),
    status: o.status,
    payment_method: o.payment_method,
    payment_status: o.payment_status,
    actions: allowedActions(o),
  };
}

function toOrderDetailDto({ order, account = null, transactions = [], vouchers = [], loyalty = [] }) {
  return {
    ...toOrderListDto({ ...order, _count: { items: order.items?.length ?? 0 } }),
    recipient: recipientOf(order.customer),
    account: account ? {
      id: num(account.id), full_name: account.full_name, email: account.email,
      phone: account.phone || null, is_active: account.is_active,
    } : null,
    amounts: {
      sub_total: num(order.subTotal),
      discount: num(order.discount),
      shipping_fee: num(order.shippingFee),
      total: num(order.total),
    },
    payment: {
      method: order.payment_method,
      status: order.payment_status,
      ref: order.payment_ref || null,
      paid_at: order.paid_at || null,
      paid_amount: num(order.paid_amount),
      expires_at: order.expires_at || null,
    },
    items: (order.items || []).map((i) => ({
      id: num(i.id),
      product_id: num(i.product_id),
      product_name: i.product_name,
      variant_id: i.variant_id || null,
      quantity: i.quantity,
      unit_price: num(i.unit_price),
      discount: num(i.discount),
      net_amount: num(i.net_amount),
    })),
    // Không trả raw_payload / bank_account / nội dung chuyển khoản: trang này không cần, và
    // đó là dữ liệu ngân hàng của khách.
    transactions: transactions.map((t) => ({
      id: num(t.id),
      provider: t.provider,
      amount: num(t.amount),
      received_at: t.received_at,
      match_status: t.match_status,
      confirm_reason: t.confirm_reason || null,
      refunded_at: t.refunded_at || null,
      refunded_amount: num(t.refunded_amount),
    })),
    vouchers: vouchers.map((v) => ({
      code: v.voucher?.code || null, amount: num(v.amount), status: v.status,
    })),
    loyalty: loyalty.map((l) => ({
      points: l.points, reason: l.reason, status: l.status, created_at: l.created_at,
    })),
  };
}

module.exports = {
  ORDER_STATUSES,
  PAYMENT_STATUSES,
  PAYMENT_METHODS,
  MAX_LIMIT,
  bizDayStart,
  parseOrderListQuery,
  recipientOf,
  allowedActions,
  toOrderListDto,
  toOrderDetailDto,
};
