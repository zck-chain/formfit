import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/config.dart';

/// 轻量 token 存储（启动时由 [SharedPreferences] 注入，避免全局循环依赖）。
/// 仅 native Bearer 链路使用；Web 链路的会话在 HttpOnly cookie 中，不进此存储。
class TokenStore {
  String? _token;
  String? get token => _token;
  void setToken(String? t) => _token = t;
  bool get hasToken => _token != null && _token!.isNotEmpty;
  void clear() => _token = null;
}

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());

/// Web Cookie 会话的 CSRF token 内存存储（双提交 cookie 模式）。
///
/// - token 只保存在内存：刷新页面后由 [AuthNotifier.bootstrap] 重新调
///   `GET /api/auth/csrf` 获取，不持久化（与 HttpOnly 的 `ff_session` cookie
///   不同，csrftoken cookie 由后端 `Path=/api` 下发，前端 JS 读不到，只能从
///   `/api/auth/csrf` 的响应体取）。
/// - [sessionActive] 标记当前是否处于 Web cookie 登录态；拦截器据此决定写请求
///   是否注入 `X-CSRF-Token`（匿名写请求如登录/注册不需要）。
/// - [ensureToken] 用「单飞」保证同一时刻只有一次 csrf 请求在途，避免拦截器
///   并发触发重复请求。
class CsrfStore {
  String? _token;
  String? get token => _token;
  bool get hasToken => _token != null && _token!.isNotEmpty;
  void setToken(String? t) => _token = t;
  void clear() => _token = null;

  /// 是否处于 Web cookie 登录态。native 恒为 false。
  bool sessionActive = false;

  Future<String>? _inFlight;

  /// 返回当前 csrf；若无则用 [fetch] 拉取一次（并发调用共享同一 Future）。
  Future<String> ensureToken(Future<String> Function() fetch) {
    if (hasToken) return Future.value(_token);
    return _inFlight ??= () async {
      final t = await fetch();
      _token = t;
      return t;
    }().whenComplete(() => _inFlight = null);
  }
}

final csrfStoreProvider = Provider<CsrfStore>((ref) => CsrfStore());

/// 统一 API 异常
class ApiException implements Exception {
  final int? statusCode;
  final String message;

  /// 后端在 402/403 body 中返回的机器可读错误码，如 `pro_required` /
  /// `quota_exhausted` / `csrf_failed`。
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

  /// 后端拒绝了写操作：cookie 会话缺少或携带了错误的 CSRF token。
  /// 命中时拦截器会重新获取 csrf 并重试一次，而非当作权限不足。
  bool get isCsrfFailed => statusCode == 403 && code == 'csrf_failed';

  /// 是否为未认证（token/cookie 失效），上层据此跳登录页。
  bool get isUnauthorized => statusCode == 401;

  @override
  String toString() => message;
}

/// 不带认证/CSRF 拦截器的 Dio，仅做 baseUrl、超时与统一错误包装。
///
/// 专供三条 Web cookie 认证端点使用（`/api/auth/web-login`、`/web-logout`、
/// `/csrf`），避免「获取 csrf 时又被 csrf 拦截器拦截」的递归。Web 下通过
/// `extra['withCredentials']=true` 让浏览器跨源携带 cookie（同源时浏览器自动带，
/// 显式开启更稳）。
final bareDioProvider = Provider<Dio>((ref) {
  final dio = Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 60),
      contentType: 'application/json',
      extra: kIsWeb ? const {'withCredentials': true} : null,
    ),
  );
  dio.interceptors.add(InterceptorsWrapper(
    onError: (e, handler) => handler.next(_wrapError(e)),
  ));
  return dio;
});

/// Dio 客户端 Provider，带认证分流（native Bearer / Web cookie + CSRF）与
/// 统一错误处理。
final dioProvider = Provider<Dio>((ref) {
  final tokenStore = ref.watch(tokenStoreProvider);
  final csrfStore = ref.watch(csrfStoreProvider);
  final bareDio = ref.watch(bareDioProvider);

  final dio = Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 60),
      contentType: 'application/json',
    ),
  );

  Future<String> ensureCsrf() => csrfStore.ensureToken(() async {
        // 走 bareDio：本请求是 GET，不会触发 csrf 拦截，但用 bareDio 语义更清晰，
        // 且错误会被统一包成 ApiException。
        final res = await bareDio.get<Map<String, dynamic>>('/api/auth/csrf');
        final token = res.data?['csrf'] as String?;
        if (token == null || token.isEmpty) {
          throw StateError('csrf 响应缺少 token');
        }
        csrfStore.setToken(token);
        return token;
      });

  dio.interceptors.add(
    AuthInterceptor(
      tokenStore: tokenStore,
      csrfStore: csrfStore,
      ensureCsrf: ensureCsrf,
      isWeb: kIsWeb,
      fetch: dio.fetch,
    ),
  );
  return dio;
});

/// 需要 CSRF 保护的写方法（大小写不敏感）。安全方法 GET/HEAD/OPTIONS 不注入。
const _csrfWriteMethods = {'POST', 'PUT', 'PATCH', 'DELETE'};
const _csrfHeader = 'X-CSRF-Token';
const _csrfRetriedFlag = '_csrfRetried';

/// 认证拦截器：
/// - native：有 token 时注入 `Authorization: Bearer`；
/// - Web：对 cookie 登录态下的写请求注入 `X-CSRF-Token`（缺 token 时先单飞获取）；
///   收到 403 `csrf_failed` 时清掉旧 token、重新获取并重试一次，仍失败才抛错。
///
/// 抽成可注入 [isWeb] 的类是为了在 VM 单测里覆盖 Web 分支（[kIsWeb] 是编译期
/// 常量，运行时无法切换），与 `buildAssessMultipartFile(isWeb:)` 同一思路。
class AuthInterceptor extends QueuedInterceptorsWrapper {
  AuthInterceptor({
    required this.tokenStore,
    required this.csrfStore,
    required this.ensureCsrf,
    required this.isWeb,
    required this.fetch,
  });

  final TokenStore tokenStore;
  final CsrfStore csrfStore;
  final Future<String> Function() ensureCsrf;
  final bool isWeb;
  final Future<Response<T>> Function<T>(RequestOptions options) fetch;

  bool get _cookieSession => isWeb && csrfStore.sessionActive;

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    if (isWeb) {
      // 让浏览器在跨源时也携带 ff_session cookie（同源默认携带）。
      options.extra['withCredentials'] = true;
      if (_cookieSession &&
          _csrfWriteMethods.contains(options.method.toUpperCase())) {
        try {
          options.headers[_csrfHeader] = await ensureCsrf();
        } catch (_) {
          // 取 csrf 失败时不阻塞请求：让请求照常发出，后端会 403，
          // 由 onError 的恢复逻辑再试一次。
        }
      }
    } else if (tokenStore.hasToken) {
      options.headers['Authorization'] = 'Bearer ${tokenStore.token}';
    }
    handler.next(options);
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    final ApiException apiErr = err.error is ApiException
        ? err.error! as ApiException
        : ApiException(
            _extractMessage(err),
            statusCode: err.response?.statusCode,
            code: _extractCode(err),
            data: _extractDetailMap(err),
          );

    // 仅 Web cookie 登录态下的写请求、且本请求尚未重试过，才做 csrf 恢复。
    final isWrite = _csrfWriteMethods.contains(
      err.requestOptions.method.toUpperCase(),
    );
    if (isWeb &&
        _cookieSession &&
        isWrite &&
        apiErr.isCsrfFailed &&
        err.requestOptions.extra[_csrfRetriedFlag] != true) {
      try {
        csrfStore.clear();
        final token = await ensureCsrf();
        final opts = err.requestOptions;
        opts.extra[_csrfRetriedFlag] = true;
        opts.headers[_csrfHeader] = token;
        final response = await fetch<dynamic>(opts);
        return handler.resolve(response);
      } catch (_) {
        // 重试仍失败（例如 csrf 端点也挂了、或 cookie 已失效）：
        // 落到下面，把原始 403 包成 ApiException 抛给上层提示重登。
      }
    }
    handler.next(_wrapError(err, override: apiErr));
  }
}

/// 把任意 [DioException] 包成带 [ApiException] 的版本，供上层统一 catch。
DioException _wrapError(DioException e, {ApiException? override}) {
  final api = override ??
      ApiException(
        _extractMessage(e),
        statusCode: e.response?.statusCode,
        code: _extractCode(e),
        data: _extractDetailMap(e),
      );
  return DioException(
    requestOptions: e.requestOptions,
    response: e.response,
    type: e.type,
    error: api,
  );
}

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
