import { useState, useEffect, useCallback } from 'react';
import { Row, Col, Card, Statistic, Table, Spin, Tag, Segmented, Select, Empty, Progress } from 'antd';
import ReactECharts from 'echarts-for-react';
import { useApp } from '../context/AppContext';
import { api } from '../services/api';
import { mono, chartRamp } from '../theme/monochrome';

// Trang Phân tích hành vi theo tông đơn sắc của khu quản trị (theme/monochrome.js, 28/11/2026):
// không icon / emoji trang trí, không màu cứng. Phân cấp bằng độ tương phản và khoảng trắng;
// biểu đồ dùng thang xám chartRamp, các đường phân biệt thêm bằng kiểu nét. Đỏ chỉ dành cho
// thứ cần xử lý (tìm kiếm không có kết quả).

function fmtNum(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n?.toLocaleString('vi-VN') || '0';
}

const cardTitle = (text) => <span style={{ fontWeight: 600 }}>{text}</span>;

// ── Thẻ chỉ số ───────────────────────────────────────────────────
// Tăng / giảm nói bằng HÌNH (viên nhộng đặc / rỗng) và dấu +/−, như KPICard ở Dashboard —
// thang xám thì đỏ / xanh cùng ra một mức xám, mất nghĩa.
function MetricCard({ title, value, suffix = '', change, loading, c }) {
  const hasChange = change !== undefined && change !== null;
  const up = Number(change) >= 0;
  return (
    <Card
      loading={loading}
      className="glass-panel glass-panel-elevated"
      style={{ height: '100%' }}
      styles={{ body: { padding: 18 } }}
    >
      <div style={{ color: c.sub, fontSize: 12, fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: 10 }}>
        {title}
      </div>
      <div style={{ fontSize: 27, fontWeight: 700, color: c.fg, lineHeight: 1.15, letterSpacing: '-0.02em' }}>
        {value}{suffix && <span style={{ fontSize: 14, fontWeight: 600, marginLeft: 2 }}>{suffix}</span>}
      </div>
      <div style={{ marginTop: 10, minHeight: 22 }}>
        {hasChange && (
          <span style={{ whiteSpace: 'nowrap' }}>
            <span style={{
              display: 'inline-block', fontSize: 11.5, fontWeight: 600, padding: '3px 8px', borderRadius: 20,
              border: `1px solid ${up ? c.inv : c.line}`,
              background: up ? c.inv : 'transparent',
              color: up ? c.invFg : c.sub,
            }}>
              {up ? '+' : '−'}{Math.abs(change)}%
            </span>
            <span style={{ fontSize: 11.5, color: c.mute, marginLeft: 6 }}>kỳ trước</span>
          </span>
        )}
      </div>
    </Card>
  );
}

// ── Một bước của phễu ────────────────────────────────────────────
function FunnelStage({ label, value, total, c }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div style={{
      textAlign: 'center', flex: 1, padding: '18px 12px',
      background: c.soft, borderRadius: 12, border: `1px solid ${c.line}`,
    }}>
      <div style={{ fontSize: 24, fontWeight: 700, color: c.fg }}>{fmtNum(value)}</div>
      <div style={{ fontSize: 12, color: c.sub, marginTop: 4 }}>{label}</div>
      <Progress
        percent={pct}
        showInfo={false}
        strokeColor={c.fg}
        trailColor={c.line}
        size="small"
        style={{ marginTop: 8 }}
      />
      <div style={{ fontSize: 11, fontWeight: 600, color: c.sub, marginTop: 2 }}>{pct}%</div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════
export default function BehaviorAnalytics() {
  const { isDark } = useApp();
  const c = mono(isDark);
  const ramp = chartRamp(isDark);
  const [days, setDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('overview');

  // Data states
  const [overview, setOverview] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [topProducts, setTopProducts] = useState([]);
  const [searchData, setSearchData] = useState(null);
  const [devices, setDevices] = useState([]);
  const [hourly, setHourly] = useState([]);
  const [referrers, setReferrers] = useState([]);
  const [dailyTrend, setDailyTrend] = useState([]);
  const [aiPerf, setAiPerf] = useState(null);
  const [productSort, setProductSort] = useState('views');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, fn, tp, sr, dv, hr, rf, dt, ai] = await Promise.all([
        api.analytics.behaviorOverview(days),
        api.analytics.behaviorFunnel(days),
        api.analytics.behaviorTopProducts(days, productSort, 10),
        api.analytics.behaviorSearch(days),
        api.analytics.behaviorDevices(days),
        api.analytics.behaviorHourly(1),
        api.analytics.behaviorReferrers(days),
        api.analytics.behaviorDailyTrend(30),
        api.analytics.behaviorAiPerf(days),
      ]);
      setOverview(ov);
      setFunnel(fn);
      setTopProducts(tp);
      setSearchData(sr);
      setDevices(dv);
      setHourly(hr);
      setReferrers(rf);
      setDailyTrend(dt);
      setAiPerf(ai);
    } catch (err) {
      console.error('[BehaviorAnalytics]', err);
    } finally {
      setLoading(false);
    }
  }, [days, productSort]);

  useEffect(() => { load(); }, [load]);

  const gridColor = c.lineSoft;
  const cardStyle = { boxShadow: '0 2px 16px rgba(0,0,0,0.06)' };
  const axisLabel = { color: c.sub };
  const legend = { textStyle: { color: c.sub }, bottom: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 3 };

  // ── Charts ──────────────────────────────────────────────────────

  // Xu hướng 30 ngày: lượt xem nét đậm có vùng, thêm giỏ nét đứt, mua hàng nét chấm.
  const trendChartOpt = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { ...legend, data: ['Lượt xem', 'Thêm giỏ', 'Mua hàng', 'Phiên'] },
    xAxis: { type: 'category', data: dailyTrend.map(d => d.date?.slice(5)), axisLabel, axisLine: { lineStyle: { color: c.line } }, axisTick: { show: false } },
    yAxis: [
      { type: 'value', axisLabel: { ...axisLabel, formatter: v => fmtNum(v) }, splitLine: { lineStyle: { color: gridColor } } },
    ],
    series: [
      { name: 'Lượt xem', type: 'line', data: dailyTrend.map(d => d.views), smooth: true, symbol: 'none',
        lineStyle: { color: ramp[0], width: 2.5 }, itemStyle: { color: ramp[0] },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: isDark ? 'rgba(250,250,250,0.14)' : 'rgba(10,10,10,0.10)' }, { offset: 1, color: 'rgba(0,0,0,0)' }] } } },
      { name: 'Thêm giỏ', type: 'line', data: dailyTrend.map(d => d.carts), smooth: true, symbol: 'none',
        lineStyle: { color: ramp[2], width: 2, type: 'dashed' }, itemStyle: { color: ramp[2] } },
      { name: 'Mua hàng', type: 'line', data: dailyTrend.map(d => d.purchases), smooth: true, symbol: 'none',
        lineStyle: { color: ramp[3], width: 2, type: 'dotted' }, itemStyle: { color: ramp[3] } },
      { name: 'Phiên', type: 'bar', data: dailyTrend.map(d => d.sessions), barMaxWidth: 20,
        itemStyle: { color: ramp[6], borderRadius: [4, 4, 0, 0] } },
    ],
    grid: { left: 8, right: 8, top: 16, bottom: 36, containLabel: true },
  };

  // Theo giờ: ba cột đậm -> nhạt theo thứ tự xem / giỏ / mua.
  const hourlyChartOpt = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { ...legend, data: ['Lượt xem', 'Thêm giỏ', 'Mua hàng'] },
    xAxis: { type: 'category', data: hourly.map(h => `${h.hour}h`), axisLabel, axisLine: { lineStyle: { color: c.line } }, axisTick: { show: false } },
    yAxis: { type: 'value', axisLabel, splitLine: { lineStyle: { color: gridColor } } },
    series: [
      { name: 'Lượt xem', type: 'bar', data: hourly.map(h => h.views), itemStyle: { borderRadius: [4, 4, 0, 0], color: ramp[0] }, barMaxWidth: 18 },
      { name: 'Thêm giỏ', type: 'bar', data: hourly.map(h => h.carts), itemStyle: { borderRadius: [4, 4, 0, 0], color: ramp[2] }, barMaxWidth: 18 },
      { name: 'Mua hàng', type: 'bar', data: hourly.map(h => h.purchases), itemStyle: { borderRadius: [4, 4, 0, 0], color: ramp[4] }, barMaxWidth: 18 },
    ],
    grid: { left: 8, right: 8, top: 16, bottom: 36, containLabel: true },
  };

  // Biểu đồ tròn: màu theo thứ tự lớn -> nhỏ trên thang xám. Không vẽ nhãn trên lát (lát nhỏ
  // đè chữ lên nhau) — danh sách bên cạnh có ô màu, số và phần trăm.
  const pieOpt = (data, unit) => ({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', formatter: p => `${p.name}<br/>${fmtNum(p.value)} ${unit} (${p.percent}%)` },
    series: [{
      type: 'pie', radius: ['52%', '80%'], center: ['50%', '50%'],
      data,
      label: { show: false },
      labelLine: { show: false },
      itemStyle: { borderRadius: 6, borderWidth: 2, borderColor: c.surface },
      color: data.map((_, i) => ramp[Math.min(i, ramp.length - 1)]),
    }],
  });
  const byDesc = (arr, key) => [...arr].sort((a, b) => Number(b[key] || 0) - Number(a[key] || 0));
  const devicesSorted = byDesc(devices, 'events');
  const referrersSorted = byDesc(referrers, 'events');
  const pct = (v, arr) => {
    const total = arr.reduce((s, x) => s + Number(x.events || 0), 0);
    return total > 0 ? `${Math.round((Number(v || 0) / total) * 1000) / 10}%` : '0%';
  };
  const swatch = (i) => (
    <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 3, marginRight: 8, background: ramp[Math.min(i, ramp.length - 1)], verticalAlign: 'middle' }} />
  );
  const deviceChartOpt = pieOpt(devicesSorted.map(d => ({ name: d.device, value: d.events })), 'sự kiện');
  const referrerChartOpt = pieOpt(referrersSorted.map(r => ({ name: r.source, value: r.events })), 'sự kiện');

  const rank = (i) => <span style={{ fontWeight: i < 3 ? 700 : 500, color: i < 3 ? c.fg : c.sub }}>{i + 1}</span>;

  // Product table columns
  const productColumns = [
    { title: '#', width: 40, render: (_, __, i) => rank(i) },
    {
      title: 'Sản phẩm', dataIndex: 'name', ellipsis: true, render: (name, r) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {r.image && <img src={r.image} alt="" style={{ width: 36, height: 36, objectFit: 'contain', borderRadius: 8, background: c.soft }} />}
          <span style={{ fontSize: 13, fontWeight: 600, color: c.fg }}>{name}</span>
        </div>
      ),
    },
    { title: 'Lượt xem', dataIndex: 'view_count', width: 90, sorter: (a, b) => a.view_count - b.view_count, render: v => <span style={{ fontWeight: 600 }}>{fmtNum(v)}</span> },
    { title: 'Thêm giỏ', dataIndex: 'cart_count', width: 90, sorter: (a, b) => a.cart_count - b.cart_count, render: v => fmtNum(v) },
    { title: 'Mua', dataIndex: 'purchase_count', width: 80, sorter: (a, b) => a.purchase_count - b.purchase_count, render: v => fmtNum(v) },
    { title: 'Xem → giỏ', dataIndex: 'view_to_cart', width: 90, sorter: (a, b) => a.view_to_cart - b.view_to_cart, render: v => `${v}%` },
    { title: 'Thời gian xem', dataIndex: 'avg_dwell_sec', width: 110, render: v => `${v}s` },
    {
      title: 'Điểm', dataIndex: 'behavior_score', width: 80, sorter: (a, b) => a.behavior_score - b.behavior_score,
      render: v => <span style={{ fontWeight: 700, color: c.fg }}>{fmtNum(v)}</span>,
    },
  ];

  const statTitle = (t) => <span style={{ color: c.sub }}>{t}</span>;
  const statValue = { color: c.fg, fontWeight: 700 };
  const kv = (label, value) => (
    <div>
      <div style={{ color: c.sub, fontSize: 12, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: c.fg }}>{value}</div>
    </div>
  );
  const panel = { padding: 24, background: c.soft, borderRadius: 12, border: `1px solid ${c.line}` };

  return (
    <div>
      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, color: c.fg, fontSize: 22, fontWeight: 700 }}>Phân tích hành vi</h2>
          <p style={{ margin: '4px 0 0', color: c.sub, fontSize: 13 }}>
            Hành vi người dùng trên cửa hàng — dữ liệu từ ClickHouse
          </p>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { label: 'Tổng quan', value: 'overview' },
              { label: 'Sản phẩm', value: 'products' },
              { label: 'Tìm kiếm', value: 'search' },
              { label: 'Hiệu quả AI', value: 'ai' },
            ]}
            size="middle"
          />
          <Select
            value={days}
            onChange={setDays}
            style={{ width: 130 }}
            options={[
              { value: 1, label: 'Hôm nay' },
              { value: 7, label: '7 ngày' },
              { value: 14, label: '14 ngày' },
              { value: 30, label: '30 ngày' },
            ]}
          />
        </div>
      </div>

      {/* ═══ TAB: OVERVIEW ═══ */}
      {tab === 'overview' && (
        <>
          {/* KPI Cards */}
          <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
            <Col xs={12} sm={8} lg={4}><MetricCard loading={loading} title="Tổng sự kiện" value={fmtNum(overview?.total_events)} change={overview?.events_change} c={c} /></Col>
            <Col xs={12} sm={8} lg={4}><MetricCard loading={loading} title="Phiên truy cập" value={fmtNum(overview?.unique_sessions)} change={overview?.sessions_change} c={c} /></Col>
            <Col xs={12} sm={8} lg={4}><MetricCard loading={loading} title="Lượt xem" value={fmtNum(overview?.total_views)} change={overview?.views_change} c={c} /></Col>
            <Col xs={12} sm={8} lg={4}><MetricCard loading={loading} title="Thêm giỏ" value={fmtNum(overview?.total_carts)} c={c} /></Col>
            <Col xs={12} sm={8} lg={4}><MetricCard loading={loading} title="Mua hàng" value={fmtNum(overview?.total_purchases)} change={overview?.purchases_change} c={c} /></Col>
            <Col xs={12} sm={8} lg={4}><MetricCard loading={loading} title="Tìm kiếm" value={fmtNum(overview?.total_searches)} c={c} /></Col>
          </Row>

          {/* Conversion Rates */}
          <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
            <Col xs={8}>
              <Card className="glass-panel" style={cardStyle} styles={{ body: { textAlign: 'center', padding: '24px 16px' } }}>
                <Statistic title={statTitle('Xem → thêm giỏ')} value={overview?.view_to_cart_rate || 0} suffix="%" valueStyle={statValue} loading={loading} />
              </Card>
            </Col>
            <Col xs={8}>
              <Card className="glass-panel" style={cardStyle} styles={{ body: { textAlign: 'center', padding: '24px 16px' } }}>
                <Statistic title={statTitle('Giỏ → mua hàng')} value={overview?.cart_to_purchase_rate || 0} suffix="%" valueStyle={statValue} loading={loading} />
              </Card>
            </Col>
            <Col xs={8}>
              <Card className="glass-panel" style={cardStyle} styles={{ body: { textAlign: 'center', padding: '24px 16px' } }}>
                <Statistic title={statTitle('Thời gian xem TB')} value={overview?.avg_dwell_sec || 0} suffix="s" valueStyle={statValue} loading={loading} />
              </Card>
            </Col>
          </Row>

          {/* Funnel */}
          <Card title={cardTitle('Phễu chuyển đổi')} className="glass-panel" style={{ ...cardStyle, marginBottom: 24 }}>
            {loading ? <div style={{ height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin /></div> : (
              <div style={{ display: 'flex', gap: 12, padding: '8px 0' }}>
                <FunnelStage label="Lượt xem" value={Number(funnel?.views || 0)} total={Number(funnel?.views || 1)} c={c} />
                <div style={{ display: 'flex', alignItems: 'center', color: c.mute, fontSize: 18 }}>→</div>
                <FunnelStage label="Thêm giỏ hàng" value={Number(funnel?.carts || 0)} total={Number(funnel?.views || 1)} c={c} />
                <div style={{ display: 'flex', alignItems: 'center', color: c.mute, fontSize: 18 }}>→</div>
                <FunnelStage label="Yêu thích" value={Number(funnel?.wishlists || 0)} total={Number(funnel?.views || 1)} c={c} />
                <div style={{ display: 'flex', alignItems: 'center', color: c.mute, fontSize: 18 }}>→</div>
                <FunnelStage label="Mua hàng" value={Number(funnel?.purchases || 0)} total={Number(funnel?.views || 1)} c={c} />
              </div>
            )}
          </Card>

          {/* Daily Trend + Hourly */}
          <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
            <Col xs={24} lg={14}>
              <Card title={cardTitle('Xu hướng 30 ngày')} className="glass-panel" style={cardStyle}>
                {loading ? <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin /></div>
                  : dailyTrend.length > 0 ? <ReactECharts option={trendChartOpt} style={{ height: 280 }} />
                  : <Empty description="Chưa có dữ liệu" />}
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card title={cardTitle('Hoạt động theo giờ')} className="glass-panel" style={cardStyle}>
                {loading ? <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin /></div>
                  : hourly.length > 0 ? <ReactECharts option={hourlyChartOpt} style={{ height: 280 }} />
                  : <Empty description="Chưa có dữ liệu" />}
              </Card>
            </Col>
          </Row>

          {/* Devices + Referrers */}
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <Card title={cardTitle('Thiết bị')} className="glass-panel" style={cardStyle}>
                {loading ? <Spin style={{ padding: 40 }} /> :
                  devicesSorted.length > 0 ? (
                    <div style={{ display: 'flex', alignItems: 'center' }}>
                      <ReactECharts option={deviceChartOpt} style={{ height: 220, flex: 1 }} />
                      <div style={{ flex: 1, padding: '0 16px' }}>
                        {devicesSorted.map((d, i) => (
                          <div key={d.device} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${gridColor}` }}>
                            <span style={{ color: c.fg }}>{swatch(i)}{d.device}</span>
                            <span style={{ fontWeight: 600, color: c.fg }}>
                              {fmtNum(d.sessions)} <span style={{ color: c.sub, fontWeight: 400 }}>phiên · {pct(d.events, devicesSorted)}</span>
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : <Empty description="Chưa có dữ liệu" />}
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card title={cardTitle('Nguồn truy cập')} className="glass-panel" style={cardStyle}>
                {loading ? <Spin style={{ padding: 40 }} /> :
                  referrersSorted.length > 0 ? (
                    <div style={{ display: 'flex', alignItems: 'center' }}>
                      <ReactECharts option={referrerChartOpt} style={{ height: 220, flex: 1 }} />
                      <div style={{ flex: 1, padding: '0 16px' }}>
                        {referrersSorted.map((r, i) => (
                          <div key={r.source} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${gridColor}` }}>
                            <span style={{ color: c.fg }}>{swatch(i)}{r.source}</span>
                            <span style={{ fontWeight: 600, color: c.fg }}>
                              {fmtNum(r.events)} <span style={{ color: c.sub, fontWeight: 400 }}>· {pct(r.events, referrersSorted)}</span>
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : <Empty description="Chưa có dữ liệu" />}
              </Card>
            </Col>
          </Row>
        </>
      )}

      {/* ═══ TAB: PRODUCTS ═══ */}
      {tab === 'products' && (
        <Card
          title={cardTitle('Top sản phẩm theo hành vi')}
          extra={
            <Select value={productSort} onChange={v => setProductSort(v)} style={{ width: 160 }}
              options={[
                { value: 'views', label: 'Lượt xem' },
                { value: 'carts', label: 'Thêm giỏ' },
                { value: 'purchases', label: 'Mua hàng' },
                { value: 'score', label: 'Điểm hành vi' },
              ]}
            />
          }
          className="glass-panel" style={cardStyle}
        >
          {loading ? <Spin style={{ padding: 40 }} /> : (
            <Table
              dataSource={topProducts}
              columns={productColumns}
              rowKey="product_id"
              pagination={false}
              size="small"
              style={{ background: 'transparent' }}
            />
          )}
        </Card>
      )}

      {/* ═══ TAB: SEARCH ═══ */}
      {tab === 'search' && (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <Card title={cardTitle('Top tìm kiếm')} className="glass-panel" style={cardStyle}>
              {loading ? <Spin style={{ padding: 40 }} /> : (
                <Table
                  dataSource={searchData?.top_queries || []}
                  rowKey="query"
                  pagination={false}
                  size="small"
                  columns={[
                    { title: '#', width: 40, render: (_, __, i) => rank(i) },
                    { title: 'Từ khóa', dataIndex: 'query', render: v => <span style={{ fontWeight: 600, color: c.fg }}>{v}</span> },
                    { title: 'Lần tìm', dataIndex: 'count', width: 90, sorter: (a, b) => a.count - b.count, render: v => <span style={{ fontWeight: 700 }}>{v}</span> },
                    { title: 'TB kết quả', dataIndex: 'avg_results', width: 100 },
                    { title: '0 kết quả', dataIndex: 'zero_results', width: 100,
                      render: v => (v > 0 ? <span style={{ color: c.danger, fontWeight: 600 }}>{v}</span> : <span style={{ color: c.mute }}>—</span>) },
                  ]}
                />
              )}
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card title={cardTitle('Tìm kiếm không có kết quả')} className="glass-panel" style={cardStyle}>
              <p style={{ color: c.sub, fontSize: 13, marginBottom: 16 }}>
                Khách tìm nhưng không thấy sản phẩm nào — gợi ý mặt hàng nên bổ sung vào danh mục.
              </p>
              {loading ? <Spin style={{ padding: 40 }} /> : (
                (searchData?.zero_result_queries || []).length > 0 ? (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {searchData.zero_result_queries.map(q => (
                      <Tag key={q.query} bordered style={{ fontSize: 13, padding: '3px 10px', borderRadius: 20, margin: 0, background: 'transparent', color: c.fg }}>
                        {q.query} <span style={{ color: c.sub }}>({q.count})</span>
                      </Tag>
                    ))}
                  </div>
                ) : <Empty description="Không có tìm kiếm 0 kết quả" />
              )}
            </Card>
          </Col>
        </Row>
      )}

      {/* ═══ TAB: AI INSIGHTS ═══ */}
      {tab === 'ai' && (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
            <Col xs={24} sm={8}>
              <Card className="glass-panel" style={cardStyle} styles={{ body: { textAlign: 'center', padding: 24 } }}>
                <Statistic title={statTitle('Sự kiện từ gợi ý')} value={aiPerf?.recommendation?.events || 0} valueStyle={statValue} loading={loading} />
                <div style={{ marginTop: 8, color: c.sub, fontSize: 12 }}>Tỷ lệ nhấp: {aiPerf?.recommendation?.ctr || 0}%</div>
              </Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card className="glass-panel" style={cardStyle} styles={{ body: { textAlign: 'center', padding: 24 } }}>
                <Statistic title={statTitle('Sự kiện từ chatbot')} value={aiPerf?.chatbot?.events || 0} valueStyle={statValue} loading={loading} />
                <div style={{ marginTop: 8, color: c.sub, fontSize: 12 }}>Thêm giỏ: {aiPerf?.chatbot?.carts || 0}</div>
              </Card>
            </Col>
            <Col xs={24} sm={8}>
              <Card className="glass-panel" style={cardStyle} styles={{ body: { textAlign: 'center', padding: 24 } }}>
                <Statistic title={statTitle('Độ phủ hành vi')} value={aiPerf?.coverage?.pct || 0} suffix="%" valueStyle={statValue} loading={loading} />
                <div style={{ marginTop: 8, color: c.sub, fontSize: 12 }}>
                  {fmtNum(aiPerf?.coverage?.sessions_with_data || 0)} / {fmtNum(aiPerf?.coverage?.total_sessions || 0)} phiên
                </div>
              </Card>
            </Col>
          </Row>

          <Card title={cardTitle('Hiệu quả gợi ý AI')} className="glass-panel" style={cardStyle}>
            <Row gutter={[24, 24]}>
              <Col xs={24} md={12}>
                <div style={panel}>
                  <h4 style={{ color: c.fg, margin: '0 0 16px', fontWeight: 600 }}>Bộ gợi ý sản phẩm</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    {kv('Sự kiện', fmtNum(aiPerf?.recommendation?.events || 0))}
                    {kv('Thêm giỏ từ gợi ý', fmtNum(aiPerf?.recommendation?.carts || 0))}
                    {kv('Mua từ gợi ý', fmtNum(aiPerf?.recommendation?.purchases || 0))}
                    {kv('Tỷ lệ nhấp (CTR)', `${aiPerf?.recommendation?.ctr || 0}%`)}
                  </div>
                </div>
              </Col>
              <Col xs={24} md={12}>
                <div style={panel}>
                  <h4 style={{ color: c.fg, margin: '0 0 16px', fontWeight: 600 }}>Chuyển đổi từ chatbot</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    {kv('Sự kiện từ chatbot', fmtNum(aiPerf?.chatbot?.events || 0))}
                    {kv('Thêm giỏ từ chatbot', fmtNum(aiPerf?.chatbot?.carts || 0))}
                  </div>
                  <div style={{ marginTop: 16, padding: 12, background: c.surface, borderRadius: 10, border: `1px solid ${c.line}` }}>
                    <div style={{ color: c.sub, fontSize: 12, marginBottom: 4 }}>Độ phủ dữ liệu (phiên có ≥ 5 sự kiện)</div>
                    <Progress percent={aiPerf?.coverage?.pct || 0} strokeColor={c.fg} trailColor={c.line} style={{ marginTop: 4 }} />
                  </div>
                </div>
              </Col>
            </Row>
          </Card>
        </>
      )}
    </div>
  );
}
