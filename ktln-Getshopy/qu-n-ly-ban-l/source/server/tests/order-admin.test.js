// Kiểm thử đơn vị cho quản lý đơn hàng ở trang quản trị (27/11/2026):
//   services/orderAdmin.js                 tham số lọc, dữ liệu trả ra, thao tác theo trạng thái
//   services/payment/orderLifecycle.js     markShipping (CONFIRMED -> SHIPPING)
// Không cần Postgres:
//   node --test tests/order-admin.test.js
const test = require('node:test');
const assert = require('node:assert/strict');

const oa = require('../src/services/orderAdmin');

// orderLifecycle require inventory / Prisma ở cấp module? Chỉ cần markShipping với tx giả;
// nạp lười để lỗi nạp module (nếu có) hiện rõ ở đúng test.
const loadLifecycle = () => require('../src/services/payment/orderLifecycle');

// ─── Tham số lọc ────────────────────────────────────────────────────────────

test('parseOrderListQuery: mặc định trang 1, 20 dòng, không lọc', () => {
  const r = oa.parseOrderListQuery({});
  assert.equal(r.ok, true);
  assert.equal(r.page, 1);
  assert.equal(r.limit, 20);
  assert.deepEqual(r.where, {});
  assert.equal(r.email, null);
});

test('parseOrderListQuery: trang / số dòng bị kẹp trong giới hạn', () => {
  assert.equal(oa.parseOrderListQuery({ page: '0' }).page, 1);
  assert.equal(oa.parseOrderListQuery({ page: 'abc' }).page, 1);
  assert.equal(oa.parseOrderListQuery({ limit: '5000' }).limit, oa.MAX_LIMIT);
  assert.equal(oa.parseOrderListQuery({ limit: '-3' }).limit, 1);
});

test('parseOrderListQuery: lọc trạng thái / thanh toán / phương thức hợp lệ, "all" là không lọc', () => {
  const r = oa.parseOrderListQuery({ status: 'SHIPPING', payment_status: 'PAID', payment_method: 'COD' });
  assert.deepEqual(r.where, { status: 'SHIPPING', payment_status: 'PAID', payment_method: 'COD' });
  assert.deepEqual(oa.parseOrderListQuery({ status: 'all', payment_status: '', payment_method: 'all' }).where, {});
});

test('parseOrderListQuery: giá trị lạ bị từ chối (không lọt vào where)', () => {
  for (const q of [{ status: 'shipping' }, { status: "CONFIRMED' OR 1=1" }, { payment_status: 'X' }, { payment_method: 'CARD' }]) {
    const r = oa.parseOrderListQuery(q);
    assert.equal(r.ok, false, JSON.stringify(q));
    assert.ok(r.error);
  }
});

test('parseOrderListQuery: khoảng ngày tính theo giờ Việt Nam, ngày kết thúc lấy trọn ngày', () => {
  const r = oa.parseOrderListQuery({ date_from: '2026-11-10', date_to: '2026-11-19' });
  assert.equal(r.ok, true);
  assert.equal(r.where.date.gte.toISOString(), '2026-11-09T17:00:00.000Z');
  assert.equal(r.where.date.lt.toISOString(), '2026-11-19T17:00:00.000Z');
});

test('parseOrderListQuery: ngày sai định dạng hoặc đảo ngược bị từ chối', () => {
  assert.equal(oa.parseOrderListQuery({ date_from: '10/11/2026' }).ok, false);
  assert.equal(oa.parseOrderListQuery({ date_to: '2026-13-01' }).ok, false);
  assert.equal(oa.parseOrderListQuery({ date_from: '2026-11-20', date_to: '2026-11-10' }).ok, false);
});

test('parseOrderListQuery: ô tìm — email / mã khách / mã đơn', () => {
  const byEmail = oa.parseOrderListQuery({ q: '  An.Nguyen@Gmail.com ' });
  assert.equal(byEmail.email, 'an.nguyen@gmail.com');
  assert.deepEqual(byEmail.where, {});

  assert.deepEqual(oa.parseOrderListQuery({ q: '40018' }).where, { customer_id: 40018n });
  assert.deepEqual(oa.parseOrderListQuery({ q: 'ORD-20261119-0001' }).where, { id: 'ORD-20261119-0001' });
  assert.equal(oa.parseOrderListQuery({ q: 'x'.repeat(201) }).ok, false);
});

// ─── Dữ liệu trả ra ─────────────────────────────────────────────────────────

test('recipientOf: ghép địa chỉ đủ cấp, đọc cả khoá cũ `name`', () => {
  assert.deepEqual(
    oa.recipientOf({ full_name: 'Nguyễn Văn An', phone: '0912345678', address: '12 Lê Lợi', ward: 'Phường Bến Nghé', district: 'Quận 1', province: 'Hồ Chí Minh' }),
    { name: 'Nguyễn Văn An', phone: '0912345678', email: null, address: '12 Lê Lợi, Phường Bến Nghé, Quận 1, Hồ Chí Minh' },
  );
  assert.equal(oa.recipientOf({ name: 'Bé Na' }).name, 'Bé Na');
  assert.deepEqual(oa.recipientOf(null), { name: null, phone: null, email: null, address: null });
});

test('allowedActions: đúng thao tác theo trạng thái', () => {
  const a = (status) => oa.allowedActions({ status });
  assert.deepEqual(a('PENDING_PAYMENT'), { ship: false, deliver: false, cancel: true });
  assert.deepEqual(a('CONFIRMED'), { ship: true, deliver: true, cancel: true });
  assert.deepEqual(a('SHIPPING'), { ship: false, deliver: true, cancel: true });
  for (const s of ['DELIVERED', 'COMPLETED', 'CANCELLED']) {
    assert.deepEqual(a(s), { ship: false, deliver: false, cancel: false }, s);
  }
});

test('toOrderListDto: BigInt -> Number, số dòng hàng từ _count', () => {
  const dto = oa.toOrderListDto({
    id: 'ORD-1', date: new Date('2026-11-19T02:37:07Z'), customer: { full_name: 'An', phone: '0912345678' },
    customer_id: 40018n, province: 'HCM', total: 1250000, status: 'CONFIRMED',
    payment_method: 'COD', payment_status: 'UNPAID', _count: { items: 3 },
  });
  assert.equal(dto.customer_id, 40018);
  assert.equal(dto.item_count, 3);
  assert.equal(dto.recipient_name, 'An');
  assert.deepEqual(dto.actions, { ship: true, deliver: true, cancel: true });
  assert.doesNotThrow(() => JSON.stringify(dto));
});

test('toOrderDetailDto: không lộ dữ liệu ngân hàng của giao dịch', () => {
  const dto = oa.toOrderDetailDto({
    order: {
      id: 'ORD-2', customer: {}, customer_id: null, total: 100, subTotal: 90, discount: 0, shippingFee: 10,
      status: 'DELIVERED', payment_method: 'BANK_TRANSFER', payment_status: 'PAID', items: [
        { id: 1n, product_id: 5n, product_name: 'A', quantity: 1, unit_price: 90, discount: 0, net_amount: 90 },
      ],
    },
    transactions: [{ id: 7n, provider: 'sepay', amount: 100, received_at: new Date(), match_status: 'MATCHED',
      bank_account: '0123456789', raw_payload: { secret: 1 }, content: 'CK GS-XYZ' }],
  });
  assert.equal(dto.items[0].product_id, 5);
  assert.equal(dto.item_count, 1);
  assert.deepEqual(Object.keys(dto.transactions[0]).sort(),
    ['amount', 'confirm_reason', 'id', 'match_status', 'provider', 'received_at', 'refunded_amount', 'refunded_at']);
  assert.equal(dto.account, null);
});

// ─── markShipping ───────────────────────────────────────────────────────────

function fakeTx(initialStatus) {
  const state = { status: initialStatus, updates: 0 };
  return {
    state,
    order: {
      updateMany: async ({ where, data }) => {
        if (state.status !== null && where.status === state.status) {
          state.status = data.status; state.updates++;
          return { count: 1 };
        }
        return { count: 0 };
      },
      findUnique: async () => (state.status === null ? null : { status: state.status }),
    },
  };
}

test('markShipping: CONFIRMED -> SHIPPING', async () => {
  const tx = fakeTx('CONFIRMED');
  assert.deepEqual(await loadLifecycle().markShipping(tx, 'ORD-1'), { changed: true });
  assert.equal(tx.state.status, 'SHIPPING');
});

test('markShipping: đã SHIPPING thì không làm gì (bấm hai lần)', async () => {
  const tx = fakeTx('SHIPPING');
  assert.deepEqual(await loadLifecycle().markShipping(tx, 'ORD-1'), { changed: false });
  assert.equal(tx.state.updates, 0);
});

test('markShipping: trạng thái khác bị từ chối, không đổi gì', async () => {
  for (const s of ['PENDING_PAYMENT', 'DELIVERED', 'CANCELLED']) {
    const tx = fakeTx(s);
    await assert.rejects(loadLifecycle().markShipping(tx, 'ORD-1'), /Chỉ chuyển sang đang giao/, s);
    assert.equal(tx.state.status, s);
  }
});

test('markShipping: không có đơn -> lỗi "Không tìm thấy" (route trả 404)', async () => {
  await assert.rejects(loadLifecycle().markShipping(fakeTx(null), 'ORD-X'), /^Error: Không tìm thấy/);
});
