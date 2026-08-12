import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:formfit_app/api/api_client.dart';

/// 直接驱动 [AuthInterceptor]：通过注入 isWeb=true/false，在 VM 单测里同时覆盖
/// Web cookie 链路与 native Bearer 链路（[kIsWeb] 是编译期常量，无法在运行时切换，
/// 故拦截器把它作为构造参数注入，与 buildAssessMultipartFile(isWeb:) 同一思路）。
void main() {
  late TokenStore tokenStore;
  late CsrfStore csrfStore;
  late List<RequestOptions> fetchCalls;
  late Response<dynamic> retryResponse;
  var ensureCsrfCalls = 0;
  String? csrfToReturn;
  Object? ensureCsrfError;

  setUp(() {
    tokenStore = TokenStore();
    csrfStore = CsrfStore();
    fetchCalls = <RequestOptions>[];
    ensureCsrfCalls = 0;
    csrfToReturn = 'csrf-token';
    ensureCsrfError = null;
    retryResponse = Response<dynamic>(
      requestOptions: RequestOptions(path: '/x'),
      data: {'ok': true},
      statusCode: 200,
    );
  });

  Future<String> ensureCsrf() async {
    ensureCsrfCalls++;
    if (ensureCsrfError != null) throw ensureCsrfError!;
    csrfStore.setToken(csrfToReturn!);
    return csrfToReturn!;
  }

  Future<Response<T>> fakeFetch<T>(RequestOptions options) async {
    fetchCalls.add(options);
    return retryResponse as Response<T>;
  }

  AuthInterceptor buildInterceptor({required bool isWeb}) {
    return AuthInterceptor(
      tokenStore: tokenStore,
      csrfStore: csrfStore,
      ensureCsrf: ensureCsrf,
      isWeb: isWeb,
      fetch: fakeFetch,
    );
  }

  /// 取 handler 内部的结果（protected future，这里用 dynamic 读取仅用于断言）。
  /// `resolve` 正常完成 future，而 `next(error)`/`reject` 会以 error 完成，
  /// 二者都包着 InterceptorState，这里统一捕获后返回其 state。
  Future<dynamic> stateOf(Object handler) async {
    try {
      return await ((handler as dynamic).future as Future);
    } catch (e) {
      return e;
    }
  }

  RequestOptions req(String method, String path) =>
      RequestOptions(path: path, method: method);

  /// 驱动 onError 并取回 handler 的最终状态。
  /// 必须先挂监听再调用 onError：handler.next/reject 以 error 完成内部 future，
  /// 若调用后才 await，dart:async 会先判定为未捕获异步错误。
  Future<dynamic> driveError(
      AuthInterceptor it, DioException err) async {
    final h = ErrorInterceptorHandler();
    final stateFuture = stateOf(h);
    await it.onError(err, h);
    return stateFuture;
  }

  group('Web cookie 会话（isWeb=true）', () {
    test('写请求 + 已登录：注入 X-CSRF-Token 并开启 withCredentials', () async {
      csrfStore.sessionActive = true;
      final it = buildInterceptor(isWeb: true);
      final options = req('POST', '/api/fitness/profile');
      final h = RequestInterceptorHandler();
      await it.onRequest(options, h);

      expect(options.headers['X-CSRF-Token'], 'csrf-token');
      expect(options.extra['withCredentials'], isTrue);
      expect(options.headers.containsKey('Authorization'), isFalse);
    });

    test('GET 请求不注入 CSRF（安全方法）', () async {
      csrfStore.sessionActive = true;
      final it = buildInterceptor(isWeb: true);
      final options = req('GET', '/api/auth/me');
      final h = RequestInterceptorHandler();
      await it.onRequest(options, h);

      expect(options.headers.containsKey('X-CSRF-Token'), isFalse);
      expect(options.extra['withCredentials'], isTrue);
      expect(ensureCsrfCalls, 0);
    });

    test('未建立 cookie 会话（匿名）的写请求不注入 CSRF', () async {
      final it = buildInterceptor(isWeb: true);
      final options = req('POST', '/api/auth/web-login');
      final h = RequestInterceptorHandler();
      await it.onRequest(options, h);

      expect(options.headers.containsKey('X-CSRF-Token'), isFalse);
      expect(ensureCsrfCalls, 0);
    });

    test('内存无 csrf 时写请求触发 ensureCsrf 拉取', () async {
      csrfStore.sessionActive = true;
      csrfStore.clear();
      final it = buildInterceptor(isWeb: true);
      final options = req('PUT', '/api/fitness/profile');
      final h = RequestInterceptorHandler();
      await it.onRequest(options, h);

      expect(ensureCsrfCalls, 1);
      expect(options.headers['X-CSRF-Token'], 'csrf-token');
    });

    test('403 csrf_failed：清空旧 token、重新获取并重试一次后 resolve', () async {
      csrfStore.sessionActive = true;
      csrfStore.setToken('stale-token');
      final it = buildInterceptor(isWeb: true);

      final options = req('POST', '/api/fitness/plans/generate');
      final err = DioException(
        requestOptions: options,
        type: DioExceptionType.badResponse,
        response: Response<dynamic>(
          requestOptions: options,
          statusCode: 403,
          data: {
            'detail': {'error': 'csrf_failed'}
          },
        ),
      );
      final state = await driveError(it, err);

      // 旧 token 被清，重新取了一次新 token
      expect(ensureCsrfCalls, 1);
      // 用同一份 RequestOptions 重试，携带新 token，且只重试一次
      expect(fetchCalls, hasLength(1));
      expect(fetchCalls.first.headers['X-CSRF-Token'], 'csrf-token');
      expect(fetchCalls.first.extra['_csrfRetried'], isTrue);
      // handler 以重试响应 resolve
      expect(state.data, retryResponse);
    });

    test('403 csrf_failed 重试仍失败时向下游抛错（不静默、不死循环）', () async {
      csrfStore.sessionActive = true;
      ensureCsrfError = StateError('csrf endpoint down');
      final it = buildInterceptor(isWeb: true);

      final options = req('POST', '/api/fitness/logs');
      final err = DioException(
        requestOptions: options,
        type: DioExceptionType.badResponse,
        response: Response<dynamic>(
          requestOptions: options,
          statusCode: 403,
          data: {
            'detail': {'error': 'csrf_failed'}
          },
        ),
      );
      final state = await driveError(it, err);

      expect(fetchCalls, isEmpty); // 没拿到新 csrf 就不该重试
      // 向下游 next 了一个带 ApiException(isCsrfFailed) 的 DioException
      final wrapped = state.data as DioException;
      final api = wrapped.error as ApiException;
      expect(api.isCsrfFailed, isTrue);
    });

    test('非 csrf 的 403（如权限不足）不触发重试', () async {
      csrfStore.sessionActive = true;
      final it = buildInterceptor(isWeb: true);

      final options = req('DELETE', '/api/admin/x');
      final err = DioException(
        requestOptions: options,
        type: DioExceptionType.badResponse,
        response: Response<dynamic>(
          requestOptions: options,
          statusCode: 403,
          data: {
            'detail': {'error': 'forbidden'}
          },
        ),
      );
      final h = ErrorInterceptorHandler();
      // 先挂监听，避免 handler.next 以 error 完成时被判定为未捕获异步错误。
      final stateFuture = stateOf(h);
      await it.onError(err, h);
      await stateFuture;

      expect(ensureCsrfCalls, 0);
      expect(fetchCalls, isEmpty);
    });
  });

  group('native Bearer（isWeb=false）', () {
    test('有 token 时注入 Authorization，不注入 CSRF', () async {
      tokenStore.setToken('jwt-123');
      final it = buildInterceptor(isWeb: false);
      final options = req('POST', '/api/fitness/logs');
      final h = RequestInterceptorHandler();
      await it.onRequest(options, h);

      expect(options.headers['Authorization'], 'Bearer jwt-123');
      expect(options.headers.containsKey('X-CSRF-Token'), isFalse);
      expect(options.extra.containsKey('withCredentials'), isFalse);
    });

    test('写操作返回 403 不触发 csrf 恢复（native 无 cookie 会话）', () async {
      tokenStore.setToken('jwt-123');
      final it = buildInterceptor(isWeb: false);
      final options = req('POST', '/api/fitness/logs');
      final err = DioException(
        requestOptions: options,
        type: DioExceptionType.badResponse,
        response: Response<dynamic>(
          requestOptions: options,
          statusCode: 403,
          data: {
            'detail': {'error': 'csrf_failed'}
          },
        ),
      );
      final h = ErrorInterceptorHandler();
      // 先挂监听，避免 handler.next 以 error 完成时被判定为未捕获异步错误。
      final stateFuture = stateOf(h);
      await it.onError(err, h);
      await stateFuture;

      expect(ensureCsrfCalls, 0);
      expect(fetchCalls, isEmpty);
    });
  });

  group('CsrfStore 单飞', () {
    test('并发 ensureToken 只触发一次 fetch，共享同一结果', () async {
      final store = CsrfStore();
      var calls = 0;
      final completer = Completer<String>();
      Future<String> fetch() {
        calls++;
        return completer.future;
      }

      final f1 = store.ensureToken(fetch);
      final f2 = store.ensureToken(fetch);
      expect(calls, 1); // 第二次调用复用在途 Future

      completer.complete('once');
      final results = await Future.wait([f1, f2]);
      expect(results, ['once', 'once']);
      expect(store.token, 'once');

      // 已有 token 时不再 fetch
      await store.ensureToken(fetch);
      expect(calls, 1);
    });
  });
}
