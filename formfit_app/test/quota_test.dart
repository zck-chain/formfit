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
    test('解析 quota 各功能额度，PRO remaining 为 null', () {
      final m = Membership.fromJson({
        'plan': 'free',
        'is_active': false,
        'is_pro': false,
        'features_locked': true,
        'quota': {
          'assess': {
            'feature': 'assess',
            'limit': 5,
            'used': 2,
            'remaining': 3,
            'reset_at': '2026-09-01T00:00:00Z',
          },
          'generate_plan': {
            'feature': 'generate_plan',
            'limit': 5,
            'used': 5,
            'remaining': 0,
            'reset_at': '2026-09-01T00:00:00Z',
          },
        },
      });

      final assess = m.quotaFor(QuotaFeatures.assess)!;
      expect(assess.limit, 5);
      expect(assess.used, 2);
      expect(assess.remaining, 3);
      expect(assess.isExhausted, isFalse);
      expect(assess.resetAt, isNotNull);

      final plan = m.quotaFor(QuotaFeatures.generatePlan)!;
      expect(plan.isExhausted, isTrue);
    });

    test('无 quota 字段时不报错（兼容旧后端）', () {
      final m = Membership.fromJson({
        'plan': 'pro',
        'is_active': true,
        'is_pro': true,
        'features_locked': false,
      });
      expect(m.quota, isEmpty);
      expect(m.quotaFor(QuotaFeatures.assess), isNull);
    });
  });

  group('两种 402 区分', () {
    test('quota_exhausted 被识别为门控且带结构化 data', () {
      final e = ApiException(
        '本月体态评估免费额度已用完，升级 PRO 不限次',
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

    test('PaywallReason 从 quota_exhausted 解析 feature 与重置时间', () {
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
    testWidgets('免费用户显示剩余次数与进度', (tester) async {
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

      expect(find.text('// 本月免费额度'), findsOneWidget);
      expect(find.textContaining('3 次'), findsWidgets);
      expect(find.text('开通 PRO 不限次'), findsOneWidget);
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
      expect(find.text('不限次'), findsWidgets);
      expect(find.text('开通 PRO 不限次'), findsNothing);
    });
  });
}
