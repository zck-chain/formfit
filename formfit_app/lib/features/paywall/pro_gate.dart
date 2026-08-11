
import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import '../../models/payment.dart';
import '../../providers/membership_provider.dart';
import 'paywall_screen.dart';

/// PRO 门控被用户取消（未开通）时抛出，供上层与真实错误区分。
class ProGateCancelled implements Exception {
  const ProGateCancelled();
  @override
  String toString() => 'PRO 门控已取消';
}

/// 付费墙被唤起的原因——决定标题/文案。
enum PaywallTrigger {
  /// 非 PRO 且需要 PRO（未登录态或非配额场景）。
  proRequired,

  /// 免费用户本月免费额度已用完。
  quotaExhausted,
}

/// 唤起付费墙的上下文（来源功能 + 触发原因）。
class PaywallReason {
  final PaywallTrigger trigger;

  /// 触发功能标识，见 [QuotaFeatures]（如 `assess`）。
  final String? feature;

  /// 配额用尽时的重置时间（次月 1 日 UTC）。
  final DateTime? resetAt;

  const PaywallReason({
    this.trigger = PaywallTrigger.proRequired,
    this.feature,
    this.resetAt,
  });

  bool get isQuotaExhausted => trigger == PaywallTrigger.quotaExhausted;

  /// 触发功能的中文名（优先用传入 feature，回退到 source 推断）。
  String? featureLabel(String? fallbackSource) {
    if (feature != null) return QuotaFeatures.labels[feature];
    return fallbackSource;
  }
}

/// 门控执行结果。[cancelled] 为 true 表示用户在付费墙关闭且未开通。
class ProGateResult<T> {
  final T? value;
  final bool cancelled;
  const ProGateResult._({this.value, required this.cancelled});
  factory ProGateResult.success(T value) =>
      ProGateResult._(value: value, cancelled: false);
  factory ProGateResult.cancelled() =>
      const ProGateResult._(cancelled: true);

  bool get isSuccess => !cancelled;
}

/// 从门控错误中解析付费墙唤起原因。
PaywallReason _resolveReason(Object e) {
  final api = _apiExceptionOf(e);
  if (api?.isQuotaExhausted == true) {
    final data = api!.data;
    return PaywallReason(
      trigger: PaywallTrigger.quotaExhausted,
      feature: data?['feature']?.toString(),
      resetAt: data?['reset_at'] != null
          ? DateTime.tryParse(data!['reset_at'].toString())
          : null,
    );
  }
  return const PaywallReason();
}

ApiException? _apiExceptionOf(Object e) {
  if (e is ApiException) return e;
  if (e is DioException && e.error is ApiException) return e.error as ApiException;
  return null;
}

/// 判断异常是否为后端 PRO 门控（HTTP 402 / 403 pro_required）。
bool isProRequiredError(Object e) {
  if (e is ApiException) return e.isProRequired;
  if (e is DioException) {
    final inner = e.error;
    if (inner is ApiException) return inner.isProRequired;
    final code = e.response?.statusCode;
    if (code == 402) return true;
  }
  return false;
}

/// PRO 功能门控：执行 [action]，命中 402/403 时弹出付费墙；
/// 支付成功后自动重试 [action] 一次。
///
/// [source] 为触发来源中文名（如「体态评估」），用于付费墙文案。
/// 典型用法：
/// ```dart
/// final r = await ProGate.run(context, ref, () => repo.assess(...));
/// if (r.isSuccess) { ... use r.value ... }
/// ```
class ProGate {
  static Future<ProGateResult<T>> run<T>(
    BuildContext context,
    WidgetRef ref,
    Future<T> Function() action, {
    String? source,
  }) async {
    try {
      final value = await action();
      // 成功入账后刷新会员态，让首页免费额度计数更新（失败不影响主流程）。
      if (context.mounted) {
        unawaited(
          ref
              .read(membershipProvider.notifier)
              .refresh()
              .then<void>((_) {})
              .catchError((_) {}),
        );
      }
      return ProGateResult.success(value);
    } catch (e) {
      if (!isProRequiredError(e)) rethrow;
      if (!context.mounted) rethrow;

      final reason = _resolveReason(e);
      final upgraded = await PaywallScreen.push<bool>(
        context,
        source: source,
        reason: reason,
      );
      if (upgraded != true) {
        return ProGateResult.cancelled();
      }
      // 支付成功后重试一次；若仍 402，则把错误抛给上层。
      return ProGateResult.success(await action());
    }
  }
}
