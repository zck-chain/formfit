import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import '../../api/repository.dart';
import '../../models/payment.dart';
import '../../providers/membership_provider.dart';
import 'in_app_purchase_service.dart';
import 'order_poller.dart';

/// 付费墙/购买流程的 UI 阶段。
enum PurchaseStage {
  /// 初始/展示套餐中
  idle,

  /// 加载套餐与渠道
  loading,

  /// 下单/支付/轮询/校验进行中
  processing,

  /// 支付或恢复成功
  success,

  /// 出错
  error,
}

@immutable
class PaymentState {
  final PurchaseStage stage;
  final List<String> channels;
  final List<PaymentPlan> plans;
  final String? selectedPlanCode;
  final String channel;

  /// success/error 时的提示文案。
  final String? message;

  /// 是否由「恢复购买」触发的成功（用于 UI 文案区分）。
  final bool restored;

  const PaymentState({
    this.stage = PurchaseStage.loading,
    this.channels = const [],
    this.plans = const [],
    this.selectedPlanCode,
    this.channel = 'sandbox',
    this.message,
    this.restored = false,
  });

  PaymentPlan? get selectedPlan {
    final code = selectedPlanCode;
    if (code == null) return null;
    for (final p in plans) {
      if (p.planCode == code) return p;
    }
    return null;
  }

  bool get isProcessing => stage == PurchaseStage.processing;
  bool get isLoading => stage == PurchaseStage.loading;

  PaymentState copyWith({
    PurchaseStage? stage,
    List<String>? channels,
    List<PaymentPlan>? plans,
    String? selectedPlanCode,
    String? channel,
    String? message,
    bool? restored,
  }) {
    return PaymentState(
      stage: stage ?? this.stage,
      channels: channels ?? this.channels,
      plans: plans ?? this.plans,
      selectedPlanCode: selectedPlanCode ?? this.selectedPlanCode,
      channel: channel ?? this.channel,
      message: message,
      restored: restored ?? this.restored,
    );
  }
}

/// 注入轮询器，便于测试替换。
final orderPollerProvider = Provider<OrderPoller>(
    (ref) => defaultOrderPoller(ref.read(apiRepositoryProvider)));

/// 前端已实现完整支付链路的渠道。
///
/// `sandbox` 可完整联调；`apple` 走 StoreKit。`alipay` / `wechat` 的真实
/// 客户端支付能力需引入对应 Flutter SDK 插件并申请商户凭证，当前阶段仅展示入口，
/// 点击给出「筹备中」提示，详见交付评论的跟进项。
const clientReadyPaymentChannels = {'sandbox', 'apple'};

/// 渠道是否已具备客户端支付能力。
bool isClientChannelReady(String channel) =>
    clientReadyPaymentChannels.contains(channel);

/// 渠道中文名。
String paymentChannelLabel(String channel) => switch (channel) {
      'sandbox' => '沙箱联调',
      'apple' => 'App Store',
      'alipay' => '支付宝',
      'wechat' => '微信支付',
      _ => channel,
};

/// v1 自助下单开关（构建期平台判定）。
///
/// Web 构建下后端以 `CHECKOUT_ENABLED=false` 硬关闭真实下单（`POST
/// /api/payment/orders` 返回 403 `checkout_disabled`），前端据此不渲染真实
/// 下单 CTA 与「恢复购买」入口，只展示「暂未开放/联系管理员」；native
/// （iOS/macOS）走 Apple 内购/沙箱的现有路径保持不变。
///
/// 抽成可覆盖的 provider 是为了在 VM 单测里覆盖 Web 分支（[kIsWeb] 是
/// 编译期常量，运行时无法切换），与 `AuthInterceptor.isWeb` 同一思路。
final selfServiceCheckoutEnabledProvider = Provider<bool>((ref) => !kIsWeb);

class PaymentController extends StateNotifier<PaymentState> {
  PaymentController(this._ref) : super(const PaymentState()) {
    // Web（自助下单关闭）不渲染任何下单入口，无需拉取套餐/渠道。
    if (_ref.read(selfServiceCheckoutEnabledProvider)) {
      load();
    }
  }
  final Ref _ref;

  ApiRepository get _repo => _ref.read(apiRepositoryProvider);
  OrderPoller get _poller => _ref.read(orderPollerProvider);
  InAppPurchaseService get _iap => _ref.read(inAppPurchaseProvider);

  /// 拉取可用渠道与套餐。
  Future<void> load() async {
    final previousChannel = state.channel;
    final channel = state.channels.isEmpty
        ? (await _resolveDefaultChannel())
        : previousChannel;
    if (!mounted) return;
    state = state.copyWith(
      stage: PurchaseStage.loading,
      channel: channel,
      message: null,
    );
    try {
      final plans = await _repo.listPaymentPlans(channel);
      if (!mounted) return;
      final yearly = plans.any((p) => p.planCode.contains('year'));
      final defaultCode = yearly
          ? plans.firstWhere((p) => p.planCode.contains('year')).planCode
          : (plans.isNotEmpty ? plans.first.planCode : null);
      state = state.copyWith(
        stage: PurchaseStage.idle,
        plans: plans,
        selectedPlanCode: defaultCode,
      );
    } catch (e) {
      if (!mounted) return;
      state = state.copyWith(
        stage: PurchaseStage.error,
        message: _friendlyError(e),
      );
    }
  }

  Future<String> _resolveDefaultChannel() async {
    final channels = await _repo.listPaymentChannels();
    if (mounted) state = state.copyWith(channels: channels);
    return _defaultChannel(channels);
  }

  String _defaultChannel(List<String> channels) {
    if (channels.contains('sandbox')) return 'sandbox';
    return channels.isNotEmpty ? channels.first : 'sandbox';
  }

  void selectPlan(String planCode) {
    if (state.selectedPlanCode == planCode) return;
    state = state.copyWith(selectedPlanCode: planCode);
  }

  void selectChannel(String channel) {
    if (state.channel == channel) return;
    state = state.copyWith(channel: channel, selectedPlanCode: null);
    // 渠道变化后重新拉取该渠道的 product_id。
    load();
  }

  void reset() {
    state = state.copyWith(stage: PurchaseStage.idle, message: null);
  }

  /// 开通所选套餐。返回是否成功；成功时调用方应关闭付费墙并继续原操作。
  Future<bool> purchase() async {
    final plan = state.selectedPlan;
    if (plan == null) return false;
    // alipay/wechat 凭证与原生插件未就绪：明确提示，不发起下单、不假成功。
    if (!isClientChannelReady(state.channel)) {
      state = state.copyWith(
        stage: PurchaseStage.idle,
        message: '${paymentChannelLabel(state.channel)}支付筹备中，即将上线，敬请期待',
      );
      return false;
    }
    state = state.copyWith(
      stage: PurchaseStage.processing,
      message: null,
      restored: false,
    );
    try {
      final order = await _repo.createPaymentOrder(
        planCode: plan.planCode,
        channel: state.channel,
      );
      if (!mounted) return false;

      if (state.channel == 'sandbox') {
        await _purchaseSandbox(order);
      } else if (state.channel == 'apple') {
        await _purchaseApple(order, plan);
      } else {
        throw StateError('暂不支持的支付渠道：${state.channel}');
      }
      if (!mounted) return false;

      await _ref.read(membershipProvider.notifier).refresh();
      if (!mounted) return false;
      state = state.copyWith(
        stage: PurchaseStage.success,
        message: 'PRO 已开通，开始训练吧！',
      );
      return true;
    } catch (e) {
      if (e is _PurchaseCancelled) return false;
      if (!mounted) return false;
      state = state.copyWith(
        stage: PurchaseStage.error,
        message: _friendlyError(e),
      );
      return false;
    }
  }

  Future<void> _purchaseSandbox(PaymentOrder order) async {
    // 1. 用下单凭据触发沙箱成功回调（模拟渠道服务器付款通知）。
    await _repo.confirmSandboxPayment(order);
    // 2. 轮询订单直到核销、会员生效。
    final result = await _poller.run(order.orderNo);
    if (result.timedOut) {
      throw StateError('支付确认超时，请稍后在订单中查看或重试');
    }
    if (result.isFailed) {
      throw StateError('支付未成功（${result.status?.status ?? 'unknown'}）');
    }
    if (!result.isFulfilled) {
      throw StateError('支付未完成，请重试');
    }
  }

  Future<void> _purchaseApple(
      PaymentOrder order, PaymentPlan plan) async {
    final productId = order.appleProductId ?? plan.providerProductId;
    if (productId == null || productId.isEmpty) {
      throw StateError('套餐未配置 Apple 商品');
    }
    final receipt = await _iap.purchaseAndGetReceipt(productId);
    if (receipt == null) {
      // 用户取消或未产生票据——回到空闲态，不报错。
      if (mounted) {
        state = state.copyWith(stage: PurchaseStage.idle, message: null);
      }
      throw const _PurchaseCancelled();
    }
    // 服务端校验票据并开通；返回已核销订单。
    final restored = await _repo.restorePurchase(
      channel: 'apple',
      receiptData: receipt,
    );
    if (!restored.isFulfilled) {
      throw StateError('购买已完成但开通失败，请尝试「恢复购买」');
    }
  }

  /// 恢复购买。
  Future<bool> restore() async {
    state = state.copyWith(
      stage: PurchaseStage.processing,
      message: null,
      restored: true,
    );
    try {
      if (state.channel == 'apple') {
        final receipt = await _iap.restoreReceipt();
        if (receipt == null || receipt.isEmpty) {
          if (mounted) {
            state = state.copyWith(
              stage: PurchaseStage.idle,
              message: '未找到可恢复的购买',
              restored: true,
            );
          }
          return false;
        }
        await _repo.restorePurchase(channel: 'apple', receiptData: receipt);
      } else {
        // 沙箱：有效的恢复票据只能由服务端用沙箱密钥签发（客户端无法伪造），
        // 这是安全设计——因此这里直接刷新会员态，已开通的账号会反映出来。
        // 完整的 restore 接口链路在 Apple 渠道验证。
      }

      final m = await _ref.read(membershipProvider.notifier).refresh();
      if (!mounted) return false;
      if (m.isPro) {
        state = state.copyWith(
          stage: PurchaseStage.success,
          message: '恢复成功，PRO 权益已生效',
          restored: true,
        );
        return true;
      }
      state = state.copyWith(
        stage: PurchaseStage.idle,
        message: '没有可恢复的 PRO 购买记录',
        restored: true,
      );
      return false;
    } catch (e) {
      if (!mounted) return false;
      state = state.copyWith(
        stage: PurchaseStage.error,
        message: _friendlyError(e),
        restored: true,
      );
      return false;
    }
  }

  String _friendlyError(Object e) {
    if (e is _PurchaseCancelled) return '';
    if (e is ApiException) return e.message;
    final msg = e.toString();
    // IAPError 等通常带可读 message；去掉前缀的 'Exception: '。
    final cleaned = msg.startsWith('Exception: ')
        ? msg.substring('Exception: '.length)
        : msg;
    return cleaned;
  }
}

class _PurchaseCancelled implements Exception {
  const _PurchaseCancelled();
}

final paymentControllerProvider =
    StateNotifierProvider.autoDispose<PaymentController, PaymentState>((ref) {
  return PaymentController(ref);
});
