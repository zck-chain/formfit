import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:formfit_app/api/api_client.dart';
import 'package:formfit_app/api/repository.dart';
import 'package:formfit_app/features/paywall/order_poller.dart';
import 'package:formfit_app/features/paywall/payment_controller.dart';
import 'package:formfit_app/features/paywall/paywall_screen.dart';
import 'package:formfit_app/features/paywall/pro_gate.dart';
import 'package:formfit_app/models/payment.dart';
import 'package:formfit_app/providers/membership_provider.dart';

import 'fakes/fake_api_repository.dart';

extension on WidgetTester {
  /// 推进时间并跑若干帧，让异步任务与动画 settle 到可断言状态，
  /// 但不使用 pumpAndSettle（GlowButton 有无限呼吸动画会卡住）。
  Future<void> flush({int frames = 8}) async {
    for (var i = 0; i < frames; i++) {
      await pump(const Duration(milliseconds: 50));
    }
  }
}

/// 给测试一个足够高的视口，让付费墙底部的「恢复购买」等也被构建。
void _useLargeViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(420, 1600);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  testWidgets('付费墙展示套餐并能完成沙箱购买', (tester) async {
    _useLargeViewport(tester);
    final repo = FakeApiRepository();
    final container = ProviderContainer(overrides: [
      apiRepositoryProvider.overrideWithValue(repo),
      tokenStoreProvider.overrideWithValue(TokenStore()..setToken('t')),
      orderPollerProvider.overrideWithValue(
        OrderPoller(
          (_) async => const OrderStatus(
            orderNo: 'x',
            status: OrderStatuses.fulfilled,
            isActive: true,
          ),
          delay: (_) async {},
        ),
      ),
    ]);
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: PaywallScreen()),
      ),
    );
    await tester.flush();

    // 两个套餐标题都应渲染，金额来自后端（不硬编码）。
    expect(find.text('Pro 月度会员'), findsOneWidget);
    expect(find.text('Pro 年度会员'), findsOneWidget);
    expect(find.textContaining('¥198'), findsWidgets);

    // 点击年度套餐选中它。
    await tester.tap(find.text('Pro 年度会员'));
    await tester.flush();

    // 点击开通，完成沙箱下单→确认→轮询。
    await tester.tap(find.text('立即开通 PRO'));
    await tester.flush(frames: 20);

    expect(repo.createOrderCalls, 1);
    expect(repo.confirmCalls, 1);
    expect(container.read(paymentControllerProvider).stage,
        PurchaseStage.success);
    expect(container.read(membershipProvider).valueOrNull?.isPro, isTrue);
  });

  testWidgets('付费墙有「恢复购买」入口', (tester) async {
    _useLargeViewport(tester);
    final repo = FakeApiRepository();
    final container = ProviderContainer(overrides: [
      apiRepositoryProvider.overrideWithValue(repo),
      tokenStoreProvider.overrideWithValue(TokenStore()..setToken('t')),
      orderPollerProvider.overrideWithValue(
        OrderPoller((_) async => const OrderStatus(
            orderNo: 'x',
            status: OrderStatuses.fulfilled,
            isActive: true)),
      ),
    ]);
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: PaywallScreen()),
      ),
    );
    await tester.flush();
    expect(find.text('恢复购买'), findsOneWidget);
  });

  testWidgets('Web 下隐藏下单 CTA/恢复购买/套餐，展示联系管理员提示',
      (tester) async {
    _useLargeViewport(tester);
    final repo = FakeApiRepository();
    final container = ProviderContainer(overrides: [
      apiRepositoryProvider.overrideWithValue(repo),
      tokenStoreProvider.overrideWithValue(TokenStore()..setToken('t')),
      // 模拟 Web 构建：v1 自助下单关闭。
      selfServiceCheckoutEnabledProvider.overrideWithValue(false),
    ]);
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: PaywallScreen()),
      ),
    );
    await tester.flush();

    // 不渲染真实下单 CTA 与 Apple「恢复购买」入口。
    expect(find.text('立即开通 PRO'), findsNothing);
    expect(find.text('恢复购买'), findsNothing);
    // 不渲染可下单的套餐/渠道选择。
    expect(find.text('Pro 月度会员'), findsNothing);
    expect(find.text('Pro 年度会员'), findsNothing);
    expect(find.text('选择套餐'), findsNothing);
    // 展示关闭说明。
    expect(find.text('PRO 暂未开放自助开通，请联系管理员'), findsOneWidget);
    // 未发起任何下单请求（控制器也未加载套餐/渠道）。
    expect(repo.createOrderCalls, 0);
    expect(repo.confirmCalls, 0);
  });

  testWidgets('native（自助下单开启）下 CTA 与恢复购买入口仍在',
      (tester) async {
    _useLargeViewport(tester);
    final repo = FakeApiRepository();
    final container = ProviderContainer(overrides: [
      apiRepositoryProvider.overrideWithValue(repo),
      tokenStoreProvider.overrideWithValue(TokenStore()..setToken('t')),
      orderPollerProvider.overrideWithValue(
        OrderPoller((_) async => const OrderStatus(
            orderNo: 'x',
            status: OrderStatuses.fulfilled,
            isActive: true)),
      ),
      // 显式模拟 native：下单入口保持不变（回归保护）。
      selfServiceCheckoutEnabledProvider.overrideWithValue(true),
    ]);
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: PaywallScreen()),
      ),
    );
    await tester.flush();

    expect(find.text('立即开通 PRO'), findsOneWidget);
    expect(find.text('恢复购买'), findsOneWidget);
    expect(find.text('Pro 年度会员'), findsOneWidget);
  });

  test('isProRequiredError 识别 402 与 403 pro_required', () {
    expect(
      isProRequiredError(ApiException('x', statusCode: 402)),
      isTrue,
    );
    expect(
      isProRequiredError(
          ApiException('x', statusCode: 403, code: 'pro_required')),
      isTrue,
    );
    expect(
      isProRequiredError(ApiException('x', statusCode: 403)),
      isFalse,
    );
    expect(isProRequiredError(ApiException('x', statusCode: 500)), isFalse);
  });
}
