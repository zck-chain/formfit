
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase/in_app_purchase.dart';

import '../../core/platform/platform.dart';

/// 内购服务抽象：购买/恢复后返回服务端可校验的票据。
///
/// Apple 端返回 base64 receipt（`localVerificationData`），提交到
/// `POST /api/payment/restore` 由服务端直连 Apple 校验。
/// 沙箱渠道不使用真实内购，见 [UnavailableInAppPurchase]。
abstract class InAppPurchaseService {
  Future<bool> isAvailable();

  /// 发起购买，完成后返回票据；用户取消/失败返回 null。
  Future<String?> purchaseAndGetReceipt(String productId);

  /// 恢复已购项目，返回最近一次有效票据。
  Future<String?> restoreReceipt();
}

/// 当前平台不支持内购（沙箱/Android 首发未接入）。
class UnavailableInAppPurchase implements InAppPurchaseService {
  final String reason;
  const UnavailableInAppPurchase([this.reason = '当前平台未接入内购']);

  @override
  Future<bool> isAvailable() async => false;

  @override
  Future<String?> purchaseAndGetReceipt(String productId) async => null;

  @override
  Future<String?> restoreReceipt() async => null;
}

/// 基于 `in_app_purchase` 插件的 Apple StoreKit 实现。
class AppleInAppPurchase implements InAppPurchaseService {
  final InAppPurchase _iap;
  StreamSubscription<List<PurchaseDetails>>? _sub;

  AppleInAppPurchase([InAppPurchase? iap])
      : _iap = iap ?? InAppPurchase.instance;

  @override
  Future<bool> isAvailable() => _iap.isAvailable();

  @override
  Future<String?> purchaseAndGetReceipt(String productId) {
    return _runTransaction(productId, restoring: false);
  }

  @override
  Future<String?> restoreReceipt() {
    return _runTransaction(null, restoring: true);
  }

  Future<String?> _runTransaction(String? productId,
      {required bool restoring}) async {
    if (!await _iap.isAvailable()) {
      throw StateError('当前设备无法连接 App Store');
    }

    final completer = Completer<String?>();
    // 必须在发起购买前建立监听，否则会漏掉本次交易结果。
    _sub = _iap.purchaseStream.listen(
      (purchases) async {
        for (final p in purchases) {
          if (completer.isCompleted) continue;
          switch (p.status) {
            case PurchaseStatus.purchased:
            case PurchaseStatus.restored:
              final receipt = p.verificationData.localVerificationData;
              await _iap.completePurchase(p);
              if (receipt.isNotEmpty) completer.complete(receipt);
              break;
            case PurchaseStatus.error:
              await _iap.completePurchase(p);
              completer.completeError(
                p.error ?? StateError('内购失败'),
              );
              break;
            case PurchaseStatus.canceled:
              await _iap.completePurchase(p);
              completer.complete(null);
              break;
            case PurchaseStatus.pending:
              // 等待异步结果（如家长审批），不做处理。
              break;
          }
        }
      },
      onError: (Object e) {
        if (!completer.isCompleted) completer.completeError(e);
      },
    );

    try {
      if (restoring) {
        await _iap.restorePurchases();
      } else {
        final resp = await _iap.queryProductDetails({productId!});
        if (resp.notFoundIDs.isNotEmpty || resp.productDetails.isEmpty) {
          throw StateError('App Store 未找到商品：$productId');
        }
        final product = resp.productDetails.first;
        final ok = await _iap.buyNonConsumable(
          purchaseParam: PurchaseParam(productDetails: product),
        );
        if (!ok) throw StateError('发起内购失败');
      }
      return await completer.future;
    } finally {
      await _sub?.cancel();
      _sub = null;
    }
  }
}

/// 根据平台返回内购实现：iOS/macOS 用 StoreKit，其余（含 Web）返回不可用占位。
///
/// `kIsWeb` 短路优先；`dart:io` 的 `Platform` 判定被收敛到条件导入
/// （`core/platform`），Web 构建树不会直接引用 `Platform`。
InAppPurchaseService createInAppPurchase() {
  if (kIsWeb || !isApplePlatform()) {
    return const UnavailableInAppPurchase();
  }
  return AppleInAppPurchase();
}
