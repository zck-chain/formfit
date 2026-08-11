import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/repository.dart';
import '../models/payment.dart';
import '../features/paywall/in_app_purchase_service.dart';

/// 会员态。默认 [Membership.free]（功能锁定），拉取 `/api/membership` 后刷新。
///
/// App 启动 / 登录 / 支付成功后调用 [refresh]；登出时 [reset]。
class MembershipNotifier extends StateNotifier<AsyncValue<Membership>> {
  MembershipNotifier(this._ref)
      : super(const AsyncValue.data(Membership.free));
  final Ref _ref;

  bool get isPro => state.valueOrNull?.isPro ?? false;
  bool get featuresLocked => state.valueOrNull?.featuresLocked ?? true;
  Membership? get membership => state.valueOrNull;

  Future<Membership> refresh() async {
    // 未登录（无 token）时不请求，保持 free。
    if (!_ref.read(tokenStoreProvider).hasToken) {
      state = const AsyncValue.data(Membership.free);
      return Membership.free;
    }
    state = const AsyncValue.loading();
    try {
      final m = await _ref.read(apiRepositoryProvider).getMembership();
      state = AsyncValue.data(m);
      return m;
    } catch (e, st) {
      // 保留上一次已知值，避免短暂网络抖动把用户弹回付费墙。
      state = AsyncValue<Membership>.error(e, st).copyWithPrevious(state);
      rethrow;
    }
  }

  void reset() => state = const AsyncValue.data(Membership.free);
}

final membershipProvider =
    StateNotifierProvider<MembershipNotifier, AsyncValue<Membership>>((ref) {
  return MembershipNotifier(ref);
});

/// 内购服务实例（按平台选择）。
final inAppPurchaseProvider = Provider<InAppPurchaseService>((ref) {
  return createInAppPurchase();
});
