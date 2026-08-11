import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:formfit_app/api/api_client.dart';
import 'package:formfit_app/api/repository.dart';
import 'package:formfit_app/features/paywall/pro_gate.dart';
import 'package:formfit_app/models/payment.dart';
import 'package:formfit_app/providers/membership_provider.dart';
import 'package:formfit_app/widgets/quota_panel.dart';

import 'fakes/fake_api_repository.dart';

void main() {
  group('Membership / Quota 解析', () {
    test('解析共享额度池，PRO remaining 为 null', () {
      final m = Membership.fromJson({
        'plan': 'free',
        'is_active': false,
        'is_pro': false,
        'features_locked': true,
        'quota': {
          'scope': 'shared',
          'limit': 5,
          'used': 3,
          'remaining': 2,
          'reset_at': '2026-09-01T00:00:00Z',
          'breakdown': {'assess': 1, 'generate_plan': 2},
        },
      });

      final q = m.quota!;
      expect(q.scope, 'shared');
      expect(q.limit, 5);
      expect(q.used, 3);
      expect(q.remaining, 2);
      expect(q.isShared, isTrue);
      expect(q.isExhausted, isFalse);
      expect(q.isUnlimited, isFalse);
      expect(q.resetAt, isNotNull);
      expect(q.breakdown[QuotaFeatures.assess], 1);
      expect(q.breakdown[QuotaFeatures.generatePlan], 2);
    });

    test('用尽的共享池 isExhausted 为 true', () {
      final m = Membership.fromJson({
        'plan': 'free',
        'is_active': false,
        'is_pro': false,
        'features_locked': true,
        'quota': {
          'scope': 'shared',
          'limit': 5,
          'used': 5,
          'remaining': 0,
          'reset_at': '2026-09-01T00:00:00Z',
        },
      });
      expect(m.quota!.isExhausted, isTrue);
      expect(m.quota!.isUnlimited, isFalse);
    });

    test('PRO 共享额度 remaining 为 null = 不限次', () {
      final m = Membership.fromJson({
        'plan': 'pro',
        'is_active': true,
        'is_pro': true,
        'features_locked': false,
        'quota': {
          'scope': 'shared',
          'limit': 5,
          'used': 0,
          'remaining': null,
          'reset_at': '2026-09-01T00:00:00Z',
        },
      });
      expect(m.quota!.isUnlimited, isTrue);
      expect(m.quota!.isExhausted, isFalse);
    });

    test('无 quota 字段时为 null（兼容旧后端/未登录）', () {
      final m = Membership.fromJson({
        'plan': 'pro',
        'is_active': true,
        'is_pro': true,
        'features_locked': false,
      });
      expect(m.quota, isNull);
    });
  });

  group('两种 402 区分', () {
    test('quota_exhausted 被识别为门控且带结构化 data', () {
      final e = ApiException(
        '本月免费额度已用完，升级 PRO 不限次',
        statusCode: 402,
        code: 'quota_exhausted',
        data: {
          'feature': 'assess',
          'limit': 5,
          'used': 5,
          'reset_at': '2026-09-01T00:00:00Z',
        },
      );
      expect(e.isProRequired, isTrue);
      expect(e.isQuotaExhausted, isTrue);
      expect(e.data?['feature'], 'assess');
    });

    test('普通 402 不被判定为 quota_exhausted', () {
      final e = ApiException('需要 PRO', statusCode: 402, code: 'pro_required');
      expect(e.isProRequired, isTrue);
      expect(e.isQuotaExhausted, isFalse);
    });

    test('PaywallReason 从 quota_exhausted 解析触发功能与重置时间', () {
      final reason = PaywallReason(
        trigger: PaywallTrigger.quotaExhausted,
        feature: QuotaFeatures.assess,
        resetAt: DateTime.parse('2026-09-01T00:00:00Z'),
      );
      expect(reason.isQuotaExhausted, isTrue);
      expect(reason.featureLabel(null), '体态评估');
      expect(reason.resetAt, isNotNull);
    });
  });

  group('QuotaPanel 渲染', () {
    testWidgets('免费用户显示共享剩余次数、一条进度与 breakdown', (tester) async {
      final repo = FakeApiRepository()..useFreeMembership(remaining: 3);
      final container = ProviderContainer(overrides: [
        apiRepositoryProvider.overrideWithValue(repo),
      ]);
      addTearDown(container.dispose);
      container.read(tokenStoreProvider).setToken('t');
      // 触发一次 membership 刷新，把 fake 的 free 态写入 provider。
      await container.read(membershipProvider.notifier).refresh();

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: Scaffold(body: QuotaPanel())),
        ),
      );
      await tester.pump();

      // 共享口径：一条进度，文案为「本月免费次数」。
      expect(find.text('// 本月免费次数（评估·计划共享）'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);
      expect(find.text('/ 5 次'), findsOneWidget);
      expect(find.text('开通 PRO 不限次'), findsOneWidget);
      // breakdown 拆分展示，但不暗示两个独立额度。
      expect(find.textContaining('体态评估'), findsOneWidget);
    });

    testWidgets('用尽时显示已用完并高亮', (tester) async {
      final repo = FakeApiRepository()..useFreeMembership(remaining: 0);
      final container = ProviderContainer(overrides: [
        apiRepositoryProvider.overrideWithValue(repo),
      ]);
      addTearDown(container.dispose);
      container.read(tokenStoreProvider).setToken('t');
      await container.read(membershipProvider.notifier).refresh();

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: Scaffold(body: QuotaPanel())),
        ),
      );
      await tester.pump();

      expect(find.text('0'), findsOneWidget);
      expect(find.text('本月免费次数已用完'), findsOneWidget);
    });

    testWidgets('PRO 用户显示不限次，不显示开通引导', (tester) async {
      final repo = FakeApiRepository(); // 默认 PRO
      final container = ProviderContainer(overrides: [
        apiRepositoryProvider.overrideWithValue(repo),
      ]);
      addTearDown(container.dispose);
      container.read(tokenStoreProvider).setToken('t');
      await container.read(membershipProvider.notifier).refresh();

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: Scaffold(body: QuotaPanel())),
        ),
      );
      await tester.pump();

      expect(find.text('// PRO 不限次'), findsOneWidget);
      expect(find.text('不限次'), findsOneWidget);
      expect(find.text('开通 PRO 不限次'), findsNothing);
    });
  });
}
