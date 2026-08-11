import 'dart:async';

import '../../api/repository.dart';
import '../../models/payment.dart';

/// 订单轮询终态结果。
class PollResult {
  /// 终态订单状态；超时时为最后一次拿到的状态（可能为 null）。
  final OrderStatus? status;
  final bool timedOut;

  const PollResult(this.status, {this.timedOut = false});

  bool get isFulfilled => status?.isSuccess ?? false;
  bool get isFailed => status?.isFailed ?? false;
}

/// 轮询订单状态直到「已核销且会员生效」、失败终态、或超时。
///
/// 抽成独立类是为了在不打真实网络、不依赖真实时钟的前提下做状态机单测：
/// [fetch] 提供订单状态，[delay] 与 [clock] 可在测试中注入。
class OrderPoller {
  final Future<OrderStatus> Function(String orderNo) fetch;
  final Duration interval;
  final Duration timeout;

  /// 轮询间隙的等待；默认 [Future.delayed]，测试可替换为即时完成。
  final Future<void> Function(Duration) delay;

  /// 时钟；默认 [DateTime.now]，测试可注入假时钟以验证超时分支。
  final DateTime Function() clock;

  OrderPoller(
    this.fetch, {
    this.interval = const Duration(seconds: 2),
    this.timeout = const Duration(seconds: 60),
    Future<void> Function(Duration)? delay,
    DateTime Function()? clock,
  })  : delay = delay ?? Future.delayed,
        clock = clock ?? DateTime.now;

  Future<PollResult> run(String orderNo) async {
    final deadline = clock().add(timeout);
    OrderStatus? last;

    while (true) {
      last = await fetch(orderNo);

      if (last.isSuccess) return PollResult(last);
      if (last.isFailed) return PollResult(last);
      if (!clock().isBefore(deadline)) {
        return PollResult(last, timedOut: true);
      }
      await delay(interval);
    }
  }
}

/// 用仓储构造的工厂方法，供 provider 直接使用。
OrderPoller defaultOrderPoller(ApiRepository repo) => OrderPoller(
      repo.getPaymentOrder,
      interval: const Duration(seconds: 2),
      timeout: const Duration(seconds: 60),
    );
