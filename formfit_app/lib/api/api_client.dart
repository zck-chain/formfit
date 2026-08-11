import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';

/// 轻量 token 存储（启动时由 [SharedPreferences] 注入，避免全局循环依赖）。
class TokenStore {
  String? _token;
  String? get token => _token;
  void setToken(String? t) => _token = t;
  bool get hasToken => _token != null && _token!.isNotEmpty;
  void clear() => _token = null;
}

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());

/// 统一 API 异常
class ApiException implements Exception {
  final int? statusCode;
  final String message;

  /// 后端在 402/403 body 中返回的机器可读错误码，如 `pro_required` /
  /// `quota_exhausted`。
  final String? code;

  /// 后端返回的完整结构化 detail（HTTPException 的 detail 为对象时）。
  /// 402 `quota_exhausted` 时含 `feature` / `limit` / `used` / `reset_at`。
  final Map<String, dynamic>? data;

  ApiException(this.message, {this.statusCode, this.code, this.data});

  /// 是否为 PRO 门控：HTTP 402，或 403 且 body 标记 `pro_required`。
  /// 命中时前端应弹出付费墙而非报错。
  bool get isProRequired {
    if (statusCode == 402) return true;
    if (statusCode == 403 && code == 'pro_required') return true;
    return false;
  }

  /// 免费用户本月额度已用尽（402 `quota_exhausted`）。
  bool get isQuotaExhausted => statusCode == 402 && code == 'quota_exhausted';

  @override
  String toString() => message;
}

/// Dio 客户端 Provider，带 JWT 注入与统一错误处理。
final dioProvider = Provider<Dio>((ref) {
  final tokenStore = ref.watch(tokenStoreProvider);
  final dio = Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 60),
      contentType: 'application/json',
    ),
  );

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        if (tokenStore.hasToken) {
          options.headers['Authorization'] = 'Bearer ${tokenStore.token}';
        }
        return handler.next(options);
      },
      onResponse: (response, handler) => handler.next(response),
      onError: (DioException e, handler) {
        final message = _extractMessage(e);
        final code = _extractCode(e);
        final data = _extractDetailMap(e);
        return handler.reject(
          DioException(
            requestOptions: e.requestOptions,
            response: e.response,
            type: e.type,
            error: ApiException(message,
                statusCode: e.response?.statusCode, code: code, data: data),
          ),
        );
      },
    ),
  );
  return dio;
});

/// 当后端 `detail` 是一个对象（如 402 quota_exhausted）时返回其 Map 视图。
Map<String, dynamic>? _extractDetailMap(DioException e) {
  final data = e.response?.data;
  if (data is Map && data['detail'] is Map) {
    return (data['detail'] as Map).cast<String, dynamic>();
  }
  return null;
}

String? _extractCode(DioException e) {
  final data = e.response?.data;
  if (data is Map) {
    // 402/403 结构化 detail：{"detail": {"error": "quota_exhausted", ...}}
    final detail = data['detail'];
    if (detail is Map && detail['error'] != null) {
      return detail['error'].toString();
    }
    final code = data['error'] ?? data['code'];
    if (code != null) return code.toString();
  }
  return null;
}

String _extractMessage(DioException e) {
  final data = e.response?.data;
  if (data is Map) {
    final detail = data['detail'];
    if (detail is String) return detail;
    if (detail is Map && detail['message'] != null) {
      return detail['message'].toString();
    }
    if (detail is List && detail.isNotEmpty) {
      final first = detail.first;
      if (first is Map && first['msg'] != null) return first['msg'].toString();
    }
    if (data['message'] != null) return data['message'].toString();
  }
  switch (e.type) {
    case DioExceptionType.connectionTimeout:
    case DioExceptionType.sendTimeout:
    case DioExceptionType.receiveTimeout:
      return '连接超时，请检查网络或后端是否启动';
    case DioExceptionType.connectionError:
      return '无法连接到服务器（${AppConfig.apiBaseUrl}）';
    default:
      return e.message ?? '请求失败';
  }
}
