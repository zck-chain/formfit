import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/assessment.dart';
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
}

final apiRepositoryProvider = Provider<ApiRepository>((ref) {
  return ApiRepository(ref.watch(dioProvider));
});
