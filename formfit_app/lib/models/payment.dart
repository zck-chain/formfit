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

/// 后端配额功能标识，与 `app/api/deps.py` 的 PRO_FEATURES 对齐。
///
/// 用于共享额度的 `breakdown` 展示拆分（各功能已用次数），不再对应独立额度。
class QuotaFeatures {
  QuotaFeatures._();
  static const assess = 'assess';
  static const generatePlan = 'generate_plan';

  /// 功能标识 → 中文展示名。
  static const labels = {
    assess: '体态评估',
    generatePlan: 'AI 计划',
  };
}

/// 月度免费额度（`GET /api/membership` 的 `quota`）。
///
/// 产品口径：体态评估与 AI 计划生成**共享**同一个月度额度池
/// （`scope: "shared"`），`used` 为两者合计、`remaining` 为共享剩余。
/// PRO 用户 [remaining] 为 `null`（不限次）。[breakdown] 仅用于展示各功能已用拆分。
class Quota {
  /// 额度口径，当前为 `shared`（共享池）。
  final String scope;
  final int limit;
  final int used;
  final int? remaining;
  final DateTime? resetAt;

  /// 各功能已用次数拆分，如 `{assess: 1, generate_plan: 2}`；仅展示用。
  final Map<String, int> breakdown;

  const Quota({
    this.scope = 'shared',
    required this.limit,
    required this.used,
    required this.remaining,
    this.resetAt,
    this.breakdown = const {},
  });

  /// PRO 不限次（remaining 为 null）。
  bool get isUnlimited => remaining == null;

  /// 共享池是否已用尽（仅对免费档有意义）。
  bool get isExhausted => remaining != null && remaining! <= 0;

  /// 是否为共享额度池。
  bool get isShared => scope == 'shared';

  factory Quota.fromJson(Map<String, dynamic> json) {
    final rawBreakdown = json['breakdown'];
    final breakdown = <String, int>{};
    if (rawBreakdown is Map) {
      rawBreakdown.forEach((key, value) {
        if (value is num) breakdown[key.toString()] = value.toInt();
      });
    }
    return Quota(
      scope: json['scope']?.toString() ?? 'shared',
      limit: (json['limit'] as num?)?.toInt() ?? 0,
      used: (json['used'] as num?)?.toInt() ?? 0,
      remaining: (json['remaining'] as num?)?.toInt(),
      resetAt: json['reset_at'] != null
          ? DateTime.tryParse(json['reset_at'].toString())
          : null,
      breakdown: breakdown,
    );
  }
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

  /// 本月共享免费额度。PRO 用户 `remaining` 为 null（不限次）；
  /// 后端未返回（旧版本/未登录）时为 null。
  final Quota? quota;

  const Membership({
    required this.plan,
    required this.isActive,
    required this.isPro,
    this.expireAt,
    this.paymentChannel,
    required this.featuresLocked,
    this.quota,
  });

  /// 免费用户的默认态。
  static const free = Membership(
    plan: 'free',
    isActive: false,
    isPro: false,
    featuresLocked: true,
  );

  factory Membership.fromJson(Map<String, dynamic> json) {
    final rawQuota = json['quota'];
    // 新形状：quota 是单个共享对象（含顶层 limit）。旧形状（按功能的 Map）
    // 在共享口径下不再使用；遇到时安全降级为 null，不崩溃。
    Quota? quota;
    if (rawQuota is Map && rawQuota['limit'] is num) {
      quota = Quota.fromJson(rawQuota.cast<String, dynamic>());
    }
    return Membership(
      plan: json['plan']?.toString() ?? 'free',
      isActive: json['is_active'] == true,
      isPro: json['is_pro'] == true,
      expireAt: json['expire_at'] != null
          ? DateTime.tryParse(json['expire_at'].toString())
          : null,
      paymentChannel: json['payment_channel']?.toString(),
      featuresLocked: json['features_locked'] == true,
      quota: quota,
    );
  }
}
