import 'package:flutter_test/flutter_test.dart';

import 'package:formfit_app/features/paywall/order_poller.dart';
import 'package:formfit_app/models/payment.dart';

OrderStatus _status(String status, {bool active = false}) => OrderStatus(
      orderNo: 'ORD-1',
      status: status,
      isActive: active,
    );

void main() {
  group('OrderPoller 状态机', () {
    test('立即 fulfilled+active 时只请求一次并成功', () async {
      var calls = 0;
      final poller = OrderPoller(
        (_) async {
          calls++;
          return _status(OrderStatuses.fulfilled, active: true);
        },
        delay: (_) async {},
        clock: () => DateTime(2026),
      );

      final r = await poller.run('ORD-1');
      expect(r.isFulfilled, isTrue);
      expect(r.timedOut, isFalse);
      expect(calls, 1);
    });

    test('pending 后 fulfilled：会轮询直到成功', () async {
      final responses = <OrderStatus>[
        _status(OrderStatuses.pending),
        _status(OrderStatuses.pending),
        _status(OrderStatuses.fulfilled, active: true),
      ];
      var i = 0;
      var delays = 0;
      final poller = OrderPoller(
        (_) async => responses[i++],
        interval: const Duration(seconds: 2),
        delay: (_) async => delays++,
        clock: () => DateTime(2026),
      );

      final r = await poller.run('ORD-1');
      expect(r.isFulfilled, isTrue);
      expect(i, 3);
      expect(delays, 2); // 成功前等待了 2 次
    });

    test('failed 终态立即结束并标记失败', () async {
      var calls = 0;
      final poller = OrderPoller(
        (_) async {
          calls++;
          return _status(OrderStatuses.failed);
        },
        delay: (_) async {},
        clock: () => DateTime(2026),
      );

      final r = await poller.run('ORD-1');
      expect(r.isFailed, isTrue);
      expect(r.isFulfilled, isFalse);
      expect(calls, 1);
    });

    test('fulfilled 但会员未激活不算成功，继续轮询直到超时', () async {
      final start = DateTime(2026);
      var now = start;
      var calls = 0;
      final poller = OrderPoller(
        (_) async {
          calls++;
          // 每次查询推进时钟 30 秒，确保在第 3 次越过 60s 超时线。
          now = now.add(const Duration(seconds: 30));
          return _status(OrderStatuses.fulfilled, active: false);
        },
        timeout: const Duration(seconds: 60),
        delay: (_) async {},
        clock: () => now,
      );

      final r = await poller.run('ORD-1');
      expect(r.timedOut, isTrue);
      expect(r.isFulfilled, isFalse);
      expect(calls, greaterThanOrEqualTo(2));
    });

    test('超过 timeout 仍未终态时返回 timedOut', () async {
      final start = DateTime(2026);
      var now = start;
      final poller = OrderPoller(
        (_) async {
          now = now.add(const Duration(seconds: 30));
          return _status(OrderStatuses.pending);
        },
        timeout: const Duration(seconds: 60),
        delay: (_) async {},
        clock: () => now,
      );

      final r = await poller.run('ORD-1');
      expect(r.timedOut, isTrue);
      expect(r.status?.status, OrderStatuses.pending);
    });
  });
}
