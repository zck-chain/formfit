import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/assessment.dart';
import '../models/payment.dart';
import '../models/plan.dart';
import '../models/user.dart';
import 'api_client.dart';

/// 统一的后端数据访问层
class ApiRepository {
  ApiRepository(this._dio);
  final Dio _dio;

  // ---- 鉴权 ----
  Future<Map<String, dynamic>> login(String email, String password) async {
    final res = await _dio.post('/api/auth/login', data: {
      'email': email,
      'password': password,
    });
    return res.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> register(
      String email, String password, String? nickname) async {
    final res = await _dio.post('/api/auth/register', data: {
      'email': email,
      'password': password,
      if (nickname != null && nickname.isNotEmpty) 'nickname': nickname,
    });
    return res.data as Map<String, dynamic>;
  }

  // ---- 档案 ----
  Future<UserProfile> getProfile() async {
    final res = await _dio.get('/api/fitness/profile');
    return UserProfile.fromJson(res.data);
  }

  Future<UserProfile> updateProfile(UserProfile profile) async {
    final res = await _dio.put('/api/fitness/profile', data: profile.toJson());
    return UserProfile.fromJson(res.data);
  }

  // ---- 拍照评估 ----
  Future<Assessment> assess({
    required File image,
    double? heightCm,
    double? weightKg,
    int? age,
    String? gender,
  }) async {
    final form = FormData.fromMap({
      'file': await MultipartFile.fromFile(image.path, filename: 'photo.jpg'),
      if (heightCm != null) 'height_cm': heightCm.toString(),
      if (weightKg != null) 'weight_kg': weightKg.toString(),
      if (age != null) 'age': age.toString(),
      if (gender != null) 'gender': gender,
    });
    final res = await _dio.post(
      '/api/fitness/assess',
      data: form,
      options: Options(contentType: 'multipart/form-data'),
    );
    return Assessment.fromJson(res.data);
  }

  // ---- 计划 ----
  Future<Plan> generatePlan() async {
    final res = await _dio.post('/api/fitness/plans/generate', data: {});
    return Plan.fromJson(res.data);
  }

  Future<List<Plan>> listPlans() async {
    final res = await _dio.get('/api/fitness/plans');
    return (res.data as List)
        .map((e) => Plan.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  // ---- 训练记录 ----
  Future<void> saveWorkoutLog({
    int? planId,
    required String title,
    int? durationMin,
    required List<Map<String, dynamic>> sets,
  }) async {
    await _dio.post('/api/fitness/logs', data: {
      if (planId != null) 'plan_id': planId,
      'title': title,
      'duration_min': durationMin,
      'sets': sets,
    });
  }

  // ---- 会员态 ----

  /// 当前用户会员权益（`GET /api/membership`）。
  Future<Membership> getMembership() async {
    final res = await _dio.get('/api/membership');
    return Membership.fromJson(res.data as Map<String, dynamic>);
  }

  // ---- 支付 ----

  /// 可用支付渠道，如 `["sandbox","apple"]`。
  Future<List<String>> listPaymentChannels() async {
    final res = await _dio.get('/api/payment/channels');
    final data = res.data;
    if (data is Map && data['channels'] is List) {
      return (data['channels'] as List).map((e) => e.toString()).toList();
    }
    return const [];
  }

  /// 套餐目录（月/年）；金额由后端返回，前端不硬编码。
  /// 注意：与健身计划的 [listPlans] 区分，本方法专指付费套餐。
  Future<List<PaymentPlan>> listPaymentPlans(String channel) async {
    final res = await _dio.get(
      '/api/payment/plans',
      queryParameters: {'channel': channel},
    );
    return (res.data as List)
        .map((e) => PaymentPlan.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 创建订单。
  Future<PaymentOrder> createPaymentOrder({
    required String planCode,
    required String channel,
  }) async {
    final res = await _dio.post('/api/payment/orders', data: {
      'plan_code': planCode,
      'channel': channel,
    });
    return PaymentOrder.fromJson(res.data as Map<String, dynamic>);
  }

  /// 查询订单状态（轮询直到开通）。
  Future<OrderStatus> getPaymentOrder(String orderNo) async {
    final res = await _dio.get('/api/payment/orders/$orderNo');
    return OrderStatus.fromJson(res.data as Map<String, dynamic>);
  }

  /// 沙箱支付：用下单凭据直接触发成功回调，模拟「用户已付款」。
  /// 仅用于本地联调；真实渠道不会把签名交给客户端。
  Future<void> confirmSandboxPayment(PaymentOrder order) async {
    final cred = order.sandboxCredential;
    if (cred == null || !cred.isComplete) {
      throw StateError('沙箱支付凭据不完整，无法确认支付');
    }
    await _dio.post(
      cred.payUrl!,
      data: cred.callbackBody(),
      // 回调端点无鉴权；沙箱签名同时放在 header 与 body，后端任一均可校验。
      options: Options(headers: {
        'X-Sandbox-Signature': cred.sign!,
      }),
    );
  }

  /// 恢复购买（Apple IAP 票据 / 沙箱模拟票据）。
  Future<PaymentOrder> restorePurchase({
    required String channel,
    required String receiptData,
  }) async {
    final res = await _dio.post('/api/payment/restore', data: {
      'channel': channel,
      'receipt_data': receiptData,
    });
    return PaymentOrder.fromJson(res.data as Map<String, dynamic>);
  }
}

final apiRepositoryProvider = Provider<ApiRepository>((ref) {
  return ApiRepository(ref.watch(dioProvider));
});
