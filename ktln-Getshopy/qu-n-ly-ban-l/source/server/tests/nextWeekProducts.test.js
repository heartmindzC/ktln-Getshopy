// "Có thể bạn cần" — RecommendationService.getNextWeekProducts (25/11/2026).
// Không cần DB/ai-rec thật: Postgres thay bằng module giả qua require.cache, ai-rec là một HTTP
// server giả trên 127.0.0.1 (cùng cách với aiRecRealtimeChain.test.js).
//   node --test tests/nextWeekProducts.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');

const SRC = path.resolve(__dirname, '../src');
const stub = (rel, exports) => {
  const file = path.join(SRC, rel);
  require.cache[file] = { id: file, filename: file, loaded: true, exports };
};

// ── Postgres giả ──────────────────────────────────────────────────────────────
const db = { products: [], flash: null, flashItems: [], findManyArgs: null };
stub('db.js', {
  prisma: {
    product: {
      findMany: async (args) => {
        db.findManyArgs = args;
        const ids = args.where.id.in.map(String);
        // trả theo id tăng dần (không theo thứ tự yêu cầu) — như Postgres không ORDER BY
        return db.products.filter(p => ids.includes(String(p.id))).sort((a, b) => Number(a.id) - Number(b.id));
      },
    },
    flashSale: { findFirst: async () => db.flash },
    flashSaleItem: { findMany: async () => db.flashItems },
  },
});
stub('services/BehaviorService.js', {});
stub('services/KnowledgeCache.js', { ensureLoaded: async () => {} });
stub('services/ProductSpecsCache.js', { getTopSpecs: () => [] });

// ── ai-rec giả ────────────────────────────────────────────────────────────────
const plan = { status: 200, delayMs: 0, predictions: [] };
const hits = [];
const server = http.createServer((req, res) => {
  hits.push(req.url);
  const timer = setTimeout(() => {
    if (res.destroyed) return;
    res.writeHead(plan.status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(plan.status === 200
      ? { customer_id: '42', horizon_days: 7, model_type: 'poisson_gamma', predictions: plan.predictions }
      : { detail: 'Not Found' }));
  }, plan.delayMs);
  res.on('close', () => clearTimeout(timer));
});

const pred = (product_id, purchase_probability) => ({
  product_id, purchase_probability, expected_cycle_days: 14.5,
  days_since_last_purchase: 12, purchase_count: 4, reason: 'poisson_gamma',
});
const product = (id, extra = {}) => ({
  id: BigInt(id), name: `SP ${id}`, price: 100000, original_price: 120000, image: `/img/${id}.png`,
  rating: 4.5, sold: 10, category_id: 1, brand_id: 2, description: '', ...extra,
});

let RS;
test.before(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  process.env.AI_REC_URL = `http://127.0.0.1:${server.address().port}`;
  console.warn = () => {};   // cảnh báo ai-rec lỗi là đúng kịch bản, không in ra
  RS = require(path.join(SRC, 'services/RecommendationService.js'));
});
test.after(() => server.close());
test.beforeEach(() => {
  hits.length = 0;
  Object.assign(plan, { status: 200, delayMs: 0, predictions: [] });
  Object.assign(db, { products: [], flash: null, flashItems: [], findManyArgs: null });
});

test('giữ thứ tự xác suất của ai-rec, bỏ món đã xoá / hết hàng, kèm next_week', async () => {
  plan.predictions = [pred('30', 0.9), pred('10', 0.6), pred('99', 0.5), pred('20', 0.3)];
  db.products = [product(10), product(20), product(30)];   // 99 không có (đã xoá / hết hàng)
  const out = await RS.getNextWeekProducts(42);
  assert.deepEqual(out.map(p => p.id), [30, 10, 20]);
  assert.deepEqual(out[0].next_week, {
    probability: 0.9, expected_cycle_days: 14.5, days_since_last_purchase: 12, purchase_count: 4,
  });
  assert.equal(out[0].name, 'SP 30');
  assert.equal(out[0].price, 100000);
  assert.match(hits[0], /^\/api\/v1\/predict\/next-week\/customer\/42\?top_k=8&horizon_days=7$/);
  assert.deepEqual(db.findManyArgs.where.is_deleted, false);
  assert.deepEqual(db.findManyArgs.where.stock, { gt: 0 });
});

test('áp giá flash sale', async () => {
  plan.predictions = [pred('10', 0.8)];
  db.products = [product(10)];
  db.flash = { id: 1 };
  db.flashItems = [{ product_id: 10n, discount_price: 79000 }];
  // cache flash sale 60 s trong module: nạp lại module để test độc lập
  delete require.cache[path.join(SRC, 'services/RecommendationService.js')];
  const fresh = require(path.join(SRC, 'services/RecommendationService.js'));
  const [p] = await fresh.getNextWeekProducts(42);
  assert.equal(p.price, 79000);
  assert.equal(p.original_price, 100000);
});

test('ai-rec bản cũ chưa có endpoint (404) -> [] (section ẩn)', async () => {
  plan.status = 404;
  assert.deepEqual(await RS.getNextWeekProducts(42), []);
});

test('ai-rec chậm quá 2 s -> [] trong ~2 s, không treo trang', async () => {
  plan.predictions = [pred('10', 0.8)];
  plan.delayMs = 5000;
  db.products = [product(10)];
  const t = Date.now();
  assert.deepEqual(await RS.getNextWeekProducts(42), []);
  const ms = Date.now() - t;
  assert.ok(ms >= 1900 && ms < 3500, `mất ${ms} ms`);
});

test('khách vãng lai (không customerId) -> [] và không gọi ai-rec', async () => {
  assert.deepEqual(await RS.getNextWeekProducts(undefined), []);
  assert.equal(hits.length, 0);
});

test('product_id không phải số -> bỏ qua, không lỗi BigInt', async () => {
  plan.predictions = [pred('abc', 0.9), pred('10', 0.5)];
  db.products = [product(10)];
  const out = await RS.getNextWeekProducts(42);
  assert.deepEqual(out.map(p => p.id), [10]);
});

test('không có dự đoán -> [] và không truy vấn Postgres', async () => {
  plan.predictions = [];
  assert.deepEqual(await RS.getNextWeekProducts(42), []);
  assert.equal(db.findManyArgs, null);
});
