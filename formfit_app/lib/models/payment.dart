/// 支付 / 会员相关模型。
///
/// 对应后端阶段一交付的契约（`app/schemas/payment.py`）：
/// - `GET /api/payment/plans` → [PaymentPlan]
/// - `POST /api/payment/orders` / `POST /api/payment/restore` → [PaymentOrder]
/// - `GET /api/payment/orders/{order_no}` → [OrderStatus]
/// - `GET /api/membership` → [Membership]
library;

/// 支付套餐（月/年等）。
class PaymentPlan {
  final String planCode;
  final String plan; // free / pro
  final String title;
  final int durationDays;

  /// 金额，单位「分」。
  final int amountCents;
  final String currency;

  /// 渠道侧商品 id（如 Apple product_id）；sandbox 下为 null。
  final String? providerProductId;

  const PaymentPlan({
    required this.planCode,
    required this.plan,
    required this.title,
    required this.durationDays,
    required this.amountCents,
    required this.currency,
    this.providerProductId,
  });

  /// 元为单位的金额，用于展示。
  double get amount => amountCents / 100.0;

  /// 每日均价（元），用于年度套餐性价比展示。
  double get amountPerDay =>
      durationDays > 0 ? amount / durationDays : amount;

  factory PaymentPlan.fromJson(Map<String, dynamic> json) => PaymentPlan(
        planCode: json['plan_code']?.toString() ?? '',
        plan: json['plan']?.toString() ?? 'pro',
        title: json['title']?.toString() ?? '',
        durationDays: (json['duration_days'] as num?)?.toInt() ?? 0,
        amountCents: (json['amount_cents'] as num?)?.toInt() ?? 0,
        currency: json['currency']?.toString() ?? 'CNY',
        providerProductId: json['provider_product_id']?.toString(),
      );
}

/// 订单状态机取值，与后端 `Order.status` 对齐。
class OrderStatuses {
  OrderStatuses._();
  static const pending = 'pending';
  static const paid = 'paid';
  static const fulfilled = 'fulfilled';
  static const failed = 'failed';
  static const refunded = 'refunded';

  /// 已核销、会员已开通——前端以此作为成功终态。
  static const success = fulfilled;
}

/// 创建/恢复订单接口返回的完整订单（含支付凭据）。
class PaymentOrder {
  final String orderNo;
  final String plan;
  final String planCode;
  final int durationDays;
  final int amountCents;
  final String currency;
  final String paymentChannel;
  final String status;

  /// 渠道侧支付凭据：
  /// - sandbox：`{pay_url, order_no, status, sandbox:{txn_id, amount_cents, sign}}`
  /// - apple：`{provider:"apple", product_id:"..."}`
  final Map<String, dynamic> payCredential;
  final DateTime? createdAt;

  const PaymentOrder({
    required this.orderNo,
    required this.plan,
    required this.planCode,
    required this.durationDays,
    required this.amountCents,
    required this.currency,
    required this.paymentChannel,
    required this.status,
    this.payCredential = const {},
    this.createdAt,
  });

  bool get isFulfilled => status == OrderStatuses.fulfilled;

  /// 沙箱凭据：触发成功回调所需的全部参数。
  SandboxCredential? get sandboxCredential {
    if (paymentChannel != 'sandbox') return null;
    final sb = payCredential['sandbox'];
    if (sb is! Map) return null;
    return SandboxCredential(
      payUrl: payCredential['pay_url']?.toString(),
      orderNo: payCredential['order_no']?.toString() ?? orderNo,
      txnId: sb['txn_id']?.toString(),
      amountCents: (sb['amount_cents'] as num?)?.toInt() ?? amountCents,
      sign: sb['sign']?.toString(),
    );
  }

  /// Apple 凭据：商品 id。
  String? get appleProductId =>
      paymentChannel == 'apple' ? payCredential['product_id']?.toString() : null;

  factory PaymentOrder.fromJson(Map<String, dynamic> json) => PaymentOrder(
        orderNo: json['order_no']?.toString() ?? '',
        plan: json['plan']?.toString() ?? 'pro',
        planCode: json['plan_code']?.toString() ?? '',
        durationDays: (json['duration_days'] as num?)?.toInt() ?? 0,
        amountCents: (json['amount_cents'] as num?)?.toInt() ?? 0,
        currency: json['currency']?.toString() ?? 'CNY',
        paymentChannel: json['payment_channel']?.toString() ?? 'sandbox',
        status: json['status']?.toString() ?? OrderStatuses.pending,
        payCredential:
            (json['pay_credential'] as Map?)?.cast<String, dynamic>() ?? const {},
        createdAt: json['created_at'] != null
            ? DateTime.tryParse(json['created_at'].toString())
            : null,
      );
}

/// 沙箱支付凭据的结构化视图，见 `app/payment/sandbox.py`。
class SandboxCredential {
  final String? payUrl;
  final String orderNo;
  final String? txnId;
  final int amountCents;
  final String? sign;

  const SandboxCredential({
    required this.payUrl,
    required this.orderNo,
    required this.txnId,
    required this.amountCents,
    required this.sign,
  });

  bool get isComplete =>
      payUrl != null &&
      txnId != null &&
      sign != null &&
      payUrl!.isNotEmpty &&
      txnId!.isNotEmpty &&
      sign!.isNotEmpty;

  /// 触发沙箱「支付成功」回调的 JSON body。
  Map<String, dynamic> callbackBody() => {
        'order_no': orderNo,
        'txn_id': txnId,
        'status': 'success',
        'amount_cents': amountCents,
        'sign': sign,
      };
}

/// 订单查询返回的状态视图（`GET /api/payment/orders/{order_no}`）。
class OrderStatus {
  final String orderNo;
  final String status;
  final bool isActive;
  final DateTime? expireAt;

  const OrderStatus({
    required this.orderNo,
    required this.status,
    required this.isActive,
    this.expireAt,
  });

  /// 支付链路成功：订单已核销 且 会员已生效。
  bool get isSuccess => status == OrderStatuses.fulfilled && isActive;

  bool get isFailed =>
      status == OrderStatuses.failed || status == OrderStatuses.refunded;

  bool get isTerminal => isSuccess || isFailed;

  factory OrderStatus.fromJson(Map<String, dynamic> json) => OrderStatus(
        orderNo: json['order_no']?.toString() ?? '',
        status: json['status']?.toString() ?? OrderStatuses.pending,
        isActive: json['is_active'] == true,
        expireAt: json['expire_at'] != null
            ? DateTime.tryParse(json['expire_at'].toString())
            : null,
      );
}

/// 当前用户会员态（`GET /api/membership`）。
class Membership {
  final String plan; // free / pro
  final bool isActive;
  final bool isPro;
  final DateTime? expireAt;
  final String? paymentChannel;

  /// PRO 功能是否被锁定——前端据此决定是否弹付费墙。
  final bool featuresLocked;

  const Membership({
    required this.plan,
    required this.isActive,
    required this.isPro,
    this.expireAt,
    this.paymentChannel,
    required this.featuresLocked,
  });

  /// 免费用户的默认态。
  static const free = Membership(
    plan: 'free',
    isActive: false,
    isPro: false,
    featuresLocked: true,
  );

  factory Membership.fromJson(Map<String, dynamic> json) => Membership(
        plan: json['plan']?.toString() ?? 'free',
        isActive: json['is_active'] == true,
        isPro: json['is_pro'] == true,
        expireAt: json['expire_at'] != null
            ? DateTime.tryParse(json['expire_at'].toString())
            : null,
        paymentChannel: json['payment_channel']?.toString(),
        featuresLocked: json['features_locked'] == true,
      );
}
