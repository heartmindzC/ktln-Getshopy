// Tab "Đơn hàng" trong trang Quản lý chung (27/11/2026).
//
// Danh sách đơn phân trang ở MÁY CHỦ (bảng Order ~3 triệu dòng), lọc theo trạng thái / thanh
// toán / phương thức / khoảng ngày, tìm theo mã đơn, mã khách hoặc email. Ngăn chi tiết có ba
// thao tác, chỉ hiện khi trạng thái cho phép (server kiểm lại):
//   - Chuyển sang "Đang giao"  CONFIRMED -> SHIPPING           POST /b2b/orders/:id/shipping
//   - Đánh dấu đã giao         CONFIRMED | SHIPPING -> DELIVERED POST /b2b/orders/:id/delivered
//   - Huỷ đơn (bắt buộc lý do) trả kho, voucher, điểm; đơn đã thu tiền -> chờ hoàn tiền ở
//                              trang Đối soát                 POST /b2b/orders/:id/cancel
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Table, Input, Select, DatePicker, Button, Space, Drawer, Descriptions, Popconfirm, Modal,
  message, Typography, Empty, Spin, Tooltip, theme,
} from 'antd';
import { EyeOutlined, ReloadOutlined, CarOutlined, CheckCircleOutlined, StopOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { api } from '../../services/api';

const { RangePicker } = DatePicker;
const { Text } = Typography;

// Trạng thái theo nguyên tắc của khu quản trị (theme/monochrome.js): phân cấp bằng độ tương
// phản, không bằng màu; chỉ giữ ĐỎ cho huỷ / việc phải xử lý. Chấm rỗng = còn chờ, chấm đặc =
// hàng đã rời kho. Màu lấy từ token antd của ConfigProvider đơn sắc (tự đổi theo nền tối).
//   tone: 'strong' chữ chính | 'muted' chữ phụ | 'danger' đỏ
const ORDER_STATUS = {
  PENDING_PAYMENT: { text: 'Chờ thanh toán', tone: 'muted', dot: 'ring' },
  CONFIRMED: { text: 'Đã xác nhận', tone: 'strong', dot: 'ring' },
  SHIPPING: { text: 'Đang giao', tone: 'strong', dot: 'fill' },
  DELIVERED: { text: 'Đã giao', tone: 'strong', dot: 'fill' },
  COMPLETED: { text: 'Hoàn tất', tone: 'strong', dot: 'fill' },
  CANCELLED: { text: 'Đã huỷ', tone: 'danger', dot: 'fill' },
};
const PAYMENT_STATUS = {
  UNPAID: { text: 'Chưa thanh toán' },
  PENDING: { text: 'Chờ chuyển khoản' },
  PAID: { text: 'Đã thanh toán' },
  EXPIRED: { text: 'Quá hạn' },
  FAILED: { text: 'Lỗi thanh toán', tone: 'danger' },
  CANCELLED: { text: 'Đã huỷ' },
  REFUND_REQUIRED: { text: 'Cần hoàn tiền', tone: 'danger' },
  REFUNDED: { text: 'Đã hoàn tiền' },
};
const PAYMENT_METHOD = { COD: 'COD', BANK_TRANSFER: 'Chuyển khoản' };
const MATCH_STATUS = {
  MATCHED: 'Khớp đơn', LATE_MATCHED: 'Khớp trễ', UNMATCHED: 'Chưa khớp', DUPLICATE: 'Trùng',
  REFUND_REQUIRED: 'Cần hoàn tiền', REFUNDED: 'Đã hoàn tiền',
};
const LEDGER_STATUS = { HELD: 'đang giữ', COMMITTED: 'đã ghi nhận', RELEASED: 'đã trả lại' };

const toOptions = (map, allLabel) => [
  { value: 'all', label: allLabel },
  ...Object.entries(map).map(([value, v]) => ({ value, label: typeof v === 'string' ? v : v.text })),
];
const STATUS_OPTIONS = toOptions(ORDER_STATUS, 'Tất cả trạng thái đơn');
const PAYMENT_STATUS_OPTIONS = toOptions(PAYMENT_STATUS, 'Tất cả thanh toán');
const PAYMENT_METHOD_OPTIONS = toOptions(PAYMENT_METHOD, 'Mọi phương thức');

const vnd = (n) => (n === null || n === undefined ? '-' : `${Number(n).toLocaleString('vi-VN')} đ`);
const dt = (d) => (d ? dayjs(d).format('HH:mm DD/MM/YYYY') : '-');

function toneColor(token, tone) {
  if (tone === 'danger') return token.colorError;
  if (tone === 'muted') return token.colorTextSecondary;
  return token.colorText;
}

/** Trạng thái đơn: chấm nhỏ + chữ. */
function OrderStatus({ value }) {
  const { token } = theme.useToken();
  const s = ORDER_STATUS[value] || { text: value || '-', tone: 'muted', dot: 'ring' };
  const color = toneColor(token, s.tone);
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, color, whiteSpace: 'nowrap' }}>
      <span style={{
        width: 7, height: 7, borderRadius: '50%', flex: 'none', boxSizing: 'border-box',
        ...(s.dot === 'fill' ? { background: color } : { border: `1.5px solid ${color}` }),
      }} />
      {s.text}
    </span>
  );
}

/** Tiêu đề mục trong ngăn chi tiết — chữ đậm, không kẻ vạch. */
function SectionTitle({ children }) {
  return <div style={{ margin: '24px 0 10px', fontWeight: 600 }}>{children}</div>;
}

/** Dòng nhắc việc phải xử lý: chữ đỏ, viền mảnh — thay Alert (warning của theme đơn sắc là khối xám). */
function ActionNote({ children, action }) {
  const { token } = theme.useToken();
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
      border: `1px solid ${token.colorBorder}`, borderRadius: token.borderRadius, padding: '10px 14px',
      marginBottom: 16, color: token.colorError,
    }}>
      <span>{children}</span>
      {action}
    </div>
  );
}

/** Thanh toán: phương thức (chữ chính) · trạng thái (chữ phụ, đỏ khi phải xử lý). */
function PaymentInfo({ method, status }) {
  const { token } = theme.useToken();
  const s = PAYMENT_STATUS[status] || { text: status || '-' };
  // COD chưa thu là bình thường — nói đúng nghĩa thay vì "chưa thanh toán".
  const text = status === 'UNPAID' && method === 'COD' ? 'Thu khi giao' : s.text;
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <span style={{ color: token.colorText }}>{PAYMENT_METHOD[method] || method}</span>
      <span style={{ color: token.colorTextTertiary }}> · </span>
      <span style={{ color: s.tone === 'danger' ? token.colorError : token.colorTextSecondary }}>{text}</span>
    </span>
  );
}

const EMPTY_FILTERS = { status: 'all', payment_status: 'all', payment_method: 'all', range: null, q: '' };

export default function OrderManagementTab() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [rows, setRows] = useState([]);
  const [page, setPage] = useState({ current: 1, pageSize: 20, total: 0 });
  const [loading, setLoading] = useState(false);

  const [detailId, setDetailId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [acting, setActing] = useState(false);

  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState('');

  const load = useCallback(async (pg, size, f) => {
    setLoading(true);
    try {
      const res = await api.b2b.getOrders({
        page: pg,
        limit: size,
        status: f.status,
        payment_status: f.payment_status,
        payment_method: f.payment_method,
        date_from: f.range?.[0] ? f.range[0].format('YYYY-MM-DD') : '',
        date_to: f.range?.[1] ? f.range[1].format('YYYY-MM-DD') : '',
        q: f.q,
      });
      setRows(res?.data || []);
      setPage({ current: pg, pageSize: size, total: res?.total || 0 });
    } catch (e) {
      message.error(e.message || 'Không tải được danh sách đơn hàng');
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(1, 20, EMPTY_FILTERS); }, [load]);

  // Đổi bộ lọc -> quay về trang 1.
  const applyFilter = (patch) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    load(1, page.pageSize, next);
  };

  const loadDetail = useCallback(async (id) => {
    setDetailLoading(true);
    try {
      setDetail(await api.b2b.getOrder(id));
    } catch (e) {
      message.error(e.message || 'Không tải được chi tiết đơn hàng');
      setDetail(null);
    }
    setDetailLoading(false);
  }, []);

  const openDetail = (id) => {
    setDetailId(id);
    setDetail(null);
    loadDetail(id);
  };
  const closeDetail = () => { setDetailId(null); setDetail(null); };

  // Sau mỗi thao tác: nạp lại chi tiết và đúng trang danh sách đang xem.
  const runAction = async (fn, okText) => {
    setActing(true);
    try {
      const res = await fn();
      message.success(res?.message || okText);
      await Promise.all([loadDetail(detailId), load(page.current, page.pageSize, filters)]);
      return true;
    } catch (e) {
      message.error(e.message || 'Thao tác không thành công');
      return false;
    } finally {
      setActing(false);
    }
  };

  const doShip = () => runAction(() => api.b2b.shipOrder(detailId), 'Đã chuyển đơn sang đang giao');
  const doDeliver = () => runAction(() => api.payments.markDelivered(detailId), 'Đã đánh dấu giao thành công');
  const doCancel = async () => {
    const reason = cancelReason.trim();
    if (!reason) { message.warning('Vui lòng nhập lý do huỷ đơn'); return; }
    const ok = await runAction(() => api.b2b.cancelOrder(detailId, reason), 'Đã huỷ đơn hàng');
    if (ok) { setCancelOpen(false); setCancelReason(''); }
  };

  const columns = [
    {
      title: 'Mã đơn', dataIndex: 'id', key: 'id', fixed: 'left',
      render: (id) => (
        <a onClick={() => openDetail(id)} style={{ fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>{id}</a>
      ),
    },
    { title: 'Ngày đặt', dataIndex: 'date', key: 'date', render: dt },
    {
      title: 'Người nhận', key: 'recipient',
      render: (_, r) => (
        <div>
          <div>{r.recipient_name || '-'}</div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {r.recipient_phone || ''}{r.customer_id ? ` · KH #${r.customer_id}` : ' · Khách vãng lai'}
          </Text>
        </div>
      ),
    },
    { title: 'Số món', dataIndex: 'item_count', key: 'item_count', align: 'right' },
    { title: 'Tổng tiền', dataIndex: 'total', key: 'total', align: 'right', render: vnd },
    { title: 'Trạng thái', dataIndex: 'status', key: 'status', render: (s) => <OrderStatus value={s} /> },
    {
      title: 'Thanh toán', key: 'payment',
      render: (_, r) => <PaymentInfo method={r.payment_method} status={r.payment_status} />,
    },
    {
      title: '', key: 'view', fixed: 'right', width: 70,
      render: (_, r) => (
        <Tooltip title="Xem chi tiết">
          <Button size="small" icon={<EyeOutlined />} onClick={() => openDetail(r.id)} />
        </Tooltip>
      ),
    },
  ];

  const a = detail?.actions || {};
  const isCod = detail?.payment_method === 'COD';
  const isPaid = detail?.payment_status === 'PAID';

  const footer = detail && (a.ship || a.deliver || a.cancel) ? (
    <Space wrap style={{ justifyContent: 'flex-end', width: '100%' }}>
      {a.cancel && (
        <Button danger icon={<StopOutlined />} disabled={acting} onClick={() => setCancelOpen(true)}>
          Huỷ đơn
        </Button>
      )}
      {a.ship && (
        <Popconfirm
          title="Chuyển đơn sang đang giao?"
          description="Sau bước này khách không tự huỷ đơn được nữa."
          okText="Chuyển" cancelText="Thôi" onConfirm={doShip}
        >
          <Button icon={<CarOutlined />} loading={acting}>Chuyển sang đang giao</Button>
        </Popconfirm>
      )}
      {a.deliver && (
        <Popconfirm
          title="Xác nhận đã giao tới khách?"
          description={isCod
            ? 'Đơn COD sẽ được ghi nhận đã thu tiền, khách được cộng điểm thưởng.'
            : 'Khách sẽ được cộng điểm thưởng cho đơn này.'}
          okText="Đã giao" cancelText="Thôi" onConfirm={doDeliver}
        >
          <Button type="primary" icon={<CheckCircleOutlined />} loading={acting}>Đánh dấu đã giao</Button>
        </Popconfirm>
      )}
    </Space>
  ) : null;

  return (
    <>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', marginBottom: 12 }}>
        <Input.Search
          allowClear
          placeholder="Mã đơn, mã khách hoặc email khách…"
          onSearch={(v) => applyFilter({ q: v.trim() })}
          style={{ maxWidth: 320, flex: '1 1 220px' }}
        />
        <Select value={filters.status} onChange={(v) => applyFilter({ status: v })} options={STATUS_OPTIONS} style={{ width: 190 }} />
        <Select value={filters.payment_status} onChange={(v) => applyFilter({ payment_status: v })} options={PAYMENT_STATUS_OPTIONS} style={{ width: 190 }} />
        <Select value={filters.payment_method} onChange={(v) => applyFilter({ payment_method: v })} options={PAYMENT_METHOD_OPTIONS} style={{ width: 170 }} />
        <RangePicker
          value={filters.range}
          format="DD/MM/YYYY"
          placeholder={['Từ ngày', 'Đến ngày']}
          onChange={(r) => applyFilter({ range: r })}
        />
        <Tooltip title="Tải lại">
          <Button icon={<ReloadOutlined />} onClick={() => load(page.current, page.pageSize, filters)} />
        </Tooltip>
      </div>

      <Table
        dataSource={rows}
        columns={columns}
        rowKey="id"
        loading={loading}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <Empty description="Không có đơn hàng phù hợp" /> }}
        pagination={{
          current: page.current,
          pageSize: page.pageSize,
          total: page.total,
          showSizeChanger: true,
          pageSizeOptions: [20, 50, 100],
          showTotal: (t) => `${t.toLocaleString('vi-VN')} đơn hàng`,
          onChange: (pg, size) => load(pg, size, filters),
        }}
      />

      <Drawer
        title={detailId ? `Đơn hàng ${detailId}` : 'Đơn hàng'}
        open={!!detailId}
        onClose={closeDetail}
        width={760}
        footer={footer}
        destroyOnClose
      >
        {detailLoading && !detail ? (
          <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
        ) : detail ? (
          <>
            {detail.payment_status === 'REFUND_REQUIRED' && (
              <ActionNote action={<Button size="small" onClick={() => navigate('/admin/reconciliation')}>Mở trang Đối soát</Button>}>
                Đơn đã huỷ nhưng khách đã thanh toán — cần hoàn tiền.
              </ActionNote>
            )}

            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Ngày đặt">{dt(detail.date)}</Descriptions.Item>
              <Descriptions.Item label="Trạng thái"><OrderStatus value={detail.status} /></Descriptions.Item>
              <Descriptions.Item label="Thanh toán">
                <PaymentInfo method={detail.payment.method} status={detail.payment.status} />
              </Descriptions.Item>
              <Descriptions.Item label="Mã đối soát">{detail.payment.ref || '-'}</Descriptions.Item>
              <Descriptions.Item label="Thanh toán lúc">{dt(detail.payment.paid_at)}</Descriptions.Item>
              <Descriptions.Item label="Số tiền đã nhận">{vnd(detail.payment.paid_amount)}</Descriptions.Item>
            </Descriptions>

            <SectionTitle>Người nhận</SectionTitle>
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="Họ tên">{detail.recipient.name || '-'}</Descriptions.Item>
              <Descriptions.Item label="Điện thoại">{detail.recipient.phone || '-'}</Descriptions.Item>
              {detail.recipient.email && <Descriptions.Item label="Email">{detail.recipient.email}</Descriptions.Item>}
              <Descriptions.Item label="Địa chỉ">{detail.recipient.address || '-'}</Descriptions.Item>
              <Descriptions.Item label="Tài khoản">
                {detail.account ? (
                  <span>
                    #{detail.account.id} · {detail.account.full_name} · {detail.account.email}
                    {!detail.account.is_active && <Text type="danger"> · đã vô hiệu hoá</Text>}
                  </span>
                ) : 'Khách vãng lai'}
              </Descriptions.Item>
            </Descriptions>

            <SectionTitle>Sản phẩm</SectionTitle>
            <Table
              size="small" rowKey="id" pagination={false} dataSource={detail.items}
              columns={[
                { title: 'Sản phẩm', dataIndex: 'product_name', key: 'name',
                  render: (n, i) => <span>{n}{i.variant_id ? <Text type="secondary"> ({i.variant_id})</Text> : null}</span> },
                { title: 'SL', dataIndex: 'quantity', key: 'qty', align: 'right' },
                { title: 'Đơn giá', dataIndex: 'unit_price', key: 'price', align: 'right', render: vnd },
                { title: 'Giảm', dataIndex: 'discount', key: 'discount', align: 'right', render: (v) => (v ? vnd(v) : '-') },
                { title: 'Thành tiền', dataIndex: 'net_amount', key: 'net', align: 'right', render: vnd },
              ]}
            />
            <Descriptions size="small" column={1} style={{ marginTop: 12, maxWidth: 360, marginLeft: 'auto' }}>
              <Descriptions.Item label="Tạm tính">{vnd(detail.amounts.sub_total)}</Descriptions.Item>
              <Descriptions.Item label="Giảm giá">{detail.amounts.discount ? `- ${vnd(detail.amounts.discount)}` : '-'}</Descriptions.Item>
              <Descriptions.Item label="Phí giao hàng">{vnd(detail.amounts.shipping_fee)}</Descriptions.Item>
              <Descriptions.Item label={<b>Tổng cộng</b>}><b>{vnd(detail.amounts.total)}</b></Descriptions.Item>
            </Descriptions>

            {detail.transactions.length > 0 && (
              <>
                <SectionTitle>Giao dịch thanh toán</SectionTitle>
                <Table
                  size="small" rowKey="id" pagination={false} dataSource={detail.transactions}
                  columns={[
                    { title: 'Nhận lúc', dataIndex: 'received_at', key: 'at', render: dt },
                    { title: 'Nguồn', dataIndex: 'provider', key: 'provider' },
                    { title: 'Số tiền', dataIndex: 'amount', key: 'amount', align: 'right', render: vnd },
                    { title: 'Đối soát', dataIndex: 'match_status', key: 'match',
                      render: (s) => (s === 'REFUND_REQUIRED'
                        ? <Text type="danger">{MATCH_STATUS[s]}</Text>
                        : <Text type="secondary">{MATCH_STATUS[s] || s}</Text>) },
                    { title: 'Ghi chú', key: 'note',
                      render: (_, t) => t.refunded_at ? `Đã hoàn ${vnd(t.refunded_amount)} lúc ${dt(t.refunded_at)}` : (t.confirm_reason || '-') },
                  ]}
                />
              </>
            )}

            {(detail.vouchers.length > 0 || detail.loyalty.length > 0) && (
              <>
                <SectionTitle>Voucher và điểm thưởng</SectionTitle>
                <Space direction="vertical" size={4}>
                  {detail.vouchers.map((v, i) => (
                    <span key={`v${i}`}>
                      Voucher {v.code || '?'}: −{vnd(v.amount)}
                      <Text type="secondary"> · {LEDGER_STATUS[v.status] || v.status}</Text>
                    </span>
                  ))}
                  {detail.loyalty.map((l, i) => (
                    <span key={`l${i}`}>
                      {l.points > 0 ? `+${l.points}` : l.points} điểm ({l.reason})
                      <Text type="secondary"> · {LEDGER_STATUS[l.status] || l.status} · {dt(l.created_at)}</Text>
                    </span>
                  ))}
                </Space>
              </>
            )}
          </>
        ) : (
          <Empty description="Không tải được đơn hàng" />
        )}
      </Drawer>

      <Modal
        title={`Huỷ đơn ${detailId || ''}`}
        open={cancelOpen}
        onCancel={() => { if (!acting) { setCancelOpen(false); setCancelReason(''); } }}
        onOk={doCancel}
        okText="Huỷ đơn"
        okButtonProps={{ danger: true, loading: acting, disabled: !cancelReason.trim() }}
        cancelText="Đóng"
      >
        <p>Kho, voucher và điểm thưởng của đơn sẽ được trả lại.</p>
        {isPaid && (
          <p><Text type="danger">Đơn đã thanh toán: sau khi huỷ, đơn chuyển sang chờ hoàn tiền ở trang Đối soát.</Text></p>
        )}
        <Input.TextArea
          rows={3}
          maxLength={500}
          showCount
          placeholder="Lý do huỷ (bắt buộc), ví dụ: khách không nhận hàng, hết hàng…"
          value={cancelReason}
          onChange={(e) => setCancelReason(e.target.value)}
        />
      </Modal>
    </>
  );
}
