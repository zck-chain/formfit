import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:formfit_app/api/api_client.dart';
import 'package:formfit_app/api/repository.dart';
import 'package:formfit_app/features/paywall/in_app_purchase_service.dart';
import 'package:formfit_app/features/paywall/order_poller.dart';
import 'package:formfit_app/features/paywall/payment_controller.dart';
import 'package:formfit_app/models/payment.dart';
import 'package:formfit_app/providers/membership_provider.dart';

import 'fakes/fake_api_repository.dart';

class _FakeIap implements InAppPurchaseService {
  String? receiptToReturn;
  bool restoreCalled = false;
  bool purchaseCalled = false;
  Object? error;

  @override
  Future<bool> isAvailable() async => true;

  @override
  Future<String?> purchaseAndGetReceipt(String productId) async {
    purchaseCalled = true;
    if (error != null) throw error!;
    return receiptToReturn;
  }

  @override
  Future<String?> restoreReceipt() async {
    restoreCalled = true;
    if (error != null) throw error!;
    return receiptToReturn;
  }
}

ProviderContainer _container({
  required FakeApiRepository repo,
  _FakeIap? iap,
  OrderStatus pollStatus = const OrderStatus(
    orderNo: 'x',
    status: OrderStatuses.fulfilled,
    isActive: true,
  ),
}) {
  final c = ProviderContainer(overrides: [
    apiRepositoryProvider.overrideWithValue(repo),
    orderPollerProvider.overrideWithValue(
      OrderPoller((_) async => pollStatus, delay: (_) async {}),
    ),
    inAppPurchaseProvider.overrideWithValue(iap ?? _FakeIap()),
  ]);
  // 让 membershipProvider 走真实刷新（fake repo 返回 pro）。
  c.read(tokenStoreProvider).setToken('test-token');
  // 保持 autoDispose 的 paymentControllerProvider 在测试期间存活。
  final sub = c.listen(paymentControllerProvider, (_, __) {});
  addTearDown(() {
    sub.close();
    c.dispose();
  });
  return c;
}

/// 等待 controller.load() 完成（两次 await：渠道→套餐）。
Future<void> _waitForLoad() async {
  await Future<void>.delayed(Duration.zero);
  await Future<void>.delayed(Duration.zero);
  await Future<void>.delayed(Duration.zero);
}

void main() {
  group('PaymentController', () {
    test('加载渠道与套餐，默认选中年度套餐', () async {
      final repo = FakeApiRepository();
      final c = _container(repo: repo);
      final controller = c.read(paymentControllerProvider.notifier);
      // 构造时已触发 load；等待 microtask 完成。
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);

      final state = c.read(paymentControllerProvider);
      expect(state.channels, ['sandbox', 'apple']);
      expect(state.plans.length, 2);
      expect(state.selectedPlanCode, 'pro_yearly');
      expect(state.channel, 'sandbox');
      expect(state.stage, PurchaseStage.idle);
      // 引用一下避免 unused lint
      expect(controller, isNotNull);
    });

    test('sandbox 购买：下单→确认→轮询→成功', () async {
      final repo = FakeApiRepository();
      final c = _container(repo: repo);
      await _waitForLoad();

      final controller = c.read(paymentControllerProvider.notifier);
      final ok = await controller.purchase();

      expect(ok, isTrue);
      expect(repo.createOrderCalls, 1);
      expect(repo.lastChannel, 'sandbox');
      expect(repo.confirmCalls, 1);
      final state = c.read(paymentControllerProvider);
      expect(state.stage, PurchaseStage.success);
      expect(c.read(membershipProvider).valueOrNull?.isPro, isTrue);
    });

    test('apple 购买：拿到票据后调用 restore 校验开通', () async {
      final repo = FakeApiRepository();
      final iap = _FakeIap()..receiptToReturn = 'base64-receipt';
      final c = _container(repo: repo, iap: iap);
      await _waitForLoad();

      final controller = c.read(paymentControllerProvider.notifier);
      controller.selectChannel('apple');
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      // 切渠道后 load 会把默认套餐重置为年度。
      final ok = await controller.purchase();

      expect(ok, isTrue);
      expect(iap.purchaseCalled, isTrue);
      expect(repo.restoreCalls, 1);
      expect(repo.lastReceipt, 'base64-receipt');
    });

    test('apple 用户取消购买时回到空闲态，不报错', () async {
      final repo = FakeApiRepository();
      final iap = _FakeIap()..receiptToReturn = null;
      final c = _container(repo: repo, iap: iap);
      await _waitForLoad();

      final controller = c.read(paymentControllerProvider.notifier);
      controller.selectChannel('apple');
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      final ok = await controller.purchase();

      expect(ok, isFalse);
      expect(repo.restoreCalls, 0);
      final state = c.read(paymentControllerProvider);
      expect(state.stage, PurchaseStage.idle);
      expect(state.message, isNull);
    });

    test('下单失败时进入 error 阶段并保留可读信息', () async {
      final repo = FakeApiRepository()
        ..createOrderError = ApiException('pro_required', statusCode: 402);
      final c = _container(repo: repo);
      await _waitForLoad();

      final controller = c.read(paymentControllerProvider.notifier);
      final ok = await controller.purchase();

      expect(ok, isFalse);
      final state = c.read(paymentControllerProvider);
      expect(state.stage, PurchaseStage.error);
      expect(state.message, 'pro_required');
    });

    test('轮询返回 failed 时购买失败', () async {
      final repo = FakeApiRepository();
      final c = _container(
        repo: repo,
        pollStatus: const OrderStatus(
          orderNo: 'x',
          status: OrderStatuses.failed,
          isActive: false,
        ),
      );
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);

      final controller = c.read(paymentControllerProvider.notifier);
      final ok = await controller.purchase();

      expect(ok, isFalse);
      expect(c.read(paymentControllerProvider).stage, PurchaseStage.error);
    });
  });
}
