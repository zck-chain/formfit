import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:formfit_app/api/repository.dart';
import 'package:formfit_app/models/payment.dart';

/// 测试用仓储：不打真实网络，支付相关方法返回内存数据，
/// 可通过构造参数控制套餐、订单状态与异常。
class FakeApiRepository extends ApiRepository {
  FakeApiRepository() : super(Dio());

  List<PaymentPlan> plans = const [
    PaymentPlan(
      planCode: 'pro_monthly',
      plan: 'pro',
      title: 'Pro 月度会员',
      durationDays: 30,
      amountCents: 2800,
      currency: 'CNY',
    ),
    PaymentPlan(
      planCode: 'pro_yearly',
      plan: 'pro',
      title: 'Pro 年度会员',
      durationDays: 365,
      amountCents: 19800,
      currency: 'CNY',
      providerProductId: 'formfit.pro.yearly',
    ),
  ];

  List<String> channels = const ['sandbox', 'apple'];

  /// createPaymentOrder 后每次查询返回的状态序列，用于驱动轮询。
  List<OrderStatus> orderStatusSequence = const [];
  int _orderQueryCount = 0;
  int confirmCalls = 0;
  int createOrderCalls = 0;
  int restoreCalls = 0;

  /// 若设置，createPaymentOrder 会抛出此异常（模拟 402 等）。
  Object? createOrderError;

  /// 最近一次创建订单时使用的渠道。
  String? lastChannel;

  /// 最近一次恢复购买时提交的票据。
  String? lastReceipt;

  void reset() {
    _orderQueryCount = 0;
    confirmCalls = 0;
    createOrderCalls = 0;
    restoreCalls = 0;
    lastChannel = null;
    lastReceipt = null;
  }

  @override
  Future<List<String>> listPaymentChannels() async => channels;

  @override
  Future<List<PaymentPlan>> listPaymentPlans(String channel) async => plans;

  @override
  Future<PaymentOrder> createPaymentOrder({
    required String planCode,
    required String channel,
  }) async {
    createOrderCalls++;
    lastChannel = channel;
    if (createOrderError != null) throw createOrderError!;
    final plan = plans.firstWhere((p) => p.planCode == planCode);
    return PaymentOrder(
      orderNo: 'ORD-$createOrderCalls',
      plan: plan.plan,
      planCode: plan.planCode,
      durationDays: plan.durationDays,
      amountCents: plan.amountCents,
      currency: plan.currency,
      paymentChannel: channel,
      status: OrderStatuses.pending,
      payCredential: channel == 'sandbox'
          ? {
              'pay_url': 'http://test/api/payment/callback/sandbox',
              'order_no': 'ORD-$createOrderCalls',
              'status': 'pending',
              'sandbox': {
                'txn_id': 'sb_ORD-$createOrderCalls',
                'amount_cents': plan.amountCents,
                'sign': 'fake-sign',
              },
            }
          : {'provider': 'apple', 'product_id': plan.providerProductId},
    );
  }

  @override
  Future<void> confirmSandboxPayment(PaymentOrder order) async {
    confirmCalls++;
  }

  @override
  Future<OrderStatus> getPaymentOrder(String orderNo) async {
    final i = _orderQueryCount;
    _orderQueryCount++;
    if (orderStatusSequence.isEmpty) {
      return _fulfilled(orderNo);
    }
    final idx = i.clamp(0, orderStatusSequence.length - 1);
    final s = orderStatusSequence[idx];
    return OrderStatus(
      orderNo: orderNo,
      status: s.status,
      isActive: s.isActive,
      expireAt: s.expireAt,
    );
  }

  @override
  Future<PaymentOrder> restorePurchase({
    required String channel,
    required String receiptData,
  }) async {
    restoreCalls++;
    lastReceipt = receiptData;
    return const PaymentOrder(
      orderNo: 'ORD-R',
      plan: 'pro',
      planCode: 'pro_yearly',
      durationDays: 365,
      amountCents: 19800,
      currency: 'CNY',
      paymentChannel: 'apple',
      status: OrderStatuses.fulfilled,
    );
  }

  @override
  Future<Membership> getMembership() async => const Membership(
        plan: 'pro',
        isActive: true,
        isPro: true,
        featuresLocked: false,
      );

  OrderStatus _fulfilled(String orderNo) => OrderStatus(
        orderNo: orderNo,
        status: OrderStatuses.fulfilled,
        isActive: true,
      );
}

/// 用 fake 仓储覆盖 provider 的辅助扩展。
extension FakeRepositoryX on ProviderContainer {
  FakeApiRepository get fakeRepo => read(apiRepositoryProvider) as FakeApiRepository;
}
