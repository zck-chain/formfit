
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/api_client.dart';
import 'paywall_screen.dart';

/// PRO 门控被用户取消（未开通）时抛出，供上层与真实错误区分。
class ProGateCancelled implements Exception {
  const ProGateCancelled();
  @override
  String toString() => 'PRO 门控已取消';
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
      return ProGateResult.success(await action());
    } catch (e) {
      if (!isProRequiredError(e)) rethrow;
      if (!context.mounted) rethrow;

      final upgraded = await PaywallScreen.push<bool>(context, source: source);
      if (upgraded != true) {
        return ProGateResult.cancelled();
      }
      // 支付成功后重试一次；若仍 402，则把错误抛给上层。
      return ProGateResult.success(await action());
    }
  }
}
