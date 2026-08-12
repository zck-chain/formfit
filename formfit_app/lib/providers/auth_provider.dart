import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/repository.dart';
import '../api/api_client.dart';
import '../models/user.dart';
import 'membership_provider.dart';

/// 认证状态
class AuthState {
  final bool isLoading;
  final AppUser? user;
  final UserProfile? profile;
  final String? error;

  const AuthState({this.isLoading = false, this.user, this.profile, this.error});

  bool get isLoggedIn => user != null;

  AuthState copyWith({
    bool? isLoading,
    AppUser? user,
    UserProfile? profile,
    String? error,
    bool clearError = false,
  }) {
    return AuthState(
      isLoading: isLoading ?? this.isLoading,
      user: user ?? this.user,
      profile: profile ?? this.profile,
      error: clearError ? null : (error ?? this.error),
    );
  }
}

class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier(this._ref) : super(const AuthState());
  final Ref _ref;
  static const _tokenKey = 'ff_token';

  /// 启动时恢复登录态：
  /// - Web：没有持久化 token，靠浏览器 cookie。调 `GET /api/auth/me`（安全方法，
  ///   无需 CSRF），200 即已登录并标记 cookie 会话激活；401 则留在登录页。
  /// - native：从 SharedPreferences 恢复 Bearer token，再调 /me 验证。
  Future<void> bootstrap() async {
    if (kIsWeb) {
      await _bootstrapWeb();
    } else {
      await _bootstrapNative();
    }
  }

  Future<void> _bootstrapNative() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_tokenKey);
    if (token == null) return;
    _ref.read(tokenStoreProvider).setToken(token);
    try {
      final user = await _fetchMe();
      final profile = await _ref.read(apiRepositoryProvider).getProfile();
      state = AuthState(user: user, profile: profile);
      unawaited(_safeRefreshMembership());
    } catch (_) {
      // token 失效，清理
      await logout();
    }
  }

  Future<void> _bootstrapWeb() async {
    // 先预取一次 csrf（GET，安全方法）：即便此刻是匿名态，登录后建立 cookie
    // 会话的首个写请求也能直接拿到 token，不必在拦截器里临时取。失败不阻塞——
    // 拦截器的 ensureCsrf 会在真正需要时再取。
    try {
      final csrf = await _ref.read(apiRepositoryProvider).fetchCsrf();
      _ref.read(csrfStoreProvider).setToken(csrf);
    } catch (_) {}
    try {
      final user = await _fetchMe();
      _ref.read(csrfStoreProvider).sessionActive = true;
      UserProfile? profile;
      try {
        profile = await _ref.read(apiRepositoryProvider).getProfile();
      } catch (_) {}
      state = AuthState(user: user, profile: profile);
      unawaited(_safeRefreshMembership());
    } on ApiException {
      // 401 = 未登录，正常停在登录页；其他 API 错误也保持未登录态，不弹错。
    } catch (_) {
      // 连接失败等：保持未登录态。
    }
  }

  Future<void> _safeRefreshMembership() async {
    try {
      await _ref.read(membershipProvider.notifier).refresh();
    } catch (_) {
      // 网络抖动等：保留默认 free 态，不影响登录。
    }
  }

  Future<AppUser> _fetchMe() async {
    final dio = _ref.read(dioProvider);
    final res = await dio.get('/api/auth/me');
    return AppUser.fromJson(res.data);
  }

  Future<bool> login(String email, String password) async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      if (kIsWeb) {
        await _loginWeb(email, password);
      } else {
        await _loginNative(email, password);
      }
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _err(e));
      return false;
    }
  }

  Future<void> _loginNative(String email, String password) async {
    final data =
        await _ref.read(apiRepositoryProvider).login(email, password);
    await _saveAuth(data);
    final user = AppUser.fromJson(data['user']);
    UserProfile? profile;
    try {
      profile = await _ref.read(apiRepositoryProvider).getProfile();
    } catch (_) {}
    state = AuthState(user: user, profile: profile);
    unawaited(_safeRefreshMembership());
  }

  Future<void> _loginWeb(String email, String password) async {
    // web-login 通过 Set-Cookie 建立 HttpOnly 会话，响应体仅 {id, email}。
    final data =
        await _ref.read(apiRepositoryProvider).webLogin(email, password);
    // 登录后后端已轮换 csrftoken cookie：重新从 body 拿一次新 token 保活内存，
    // 保证后续写请求带的是与本次会话匹配的 csrf。
    final csrf = await _ref.read(apiRepositoryProvider).fetchCsrf();
    final csrfStore = _ref.read(csrfStoreProvider);
    csrfStore.setToken(csrf);
    csrfStore.sessionActive = true;
    // Web 不持久化任何 token 到 localStorage/SharedPreferences。
    final user = AppUser.fromJson(data);
    UserProfile? profile;
    try {
      profile = await _ref.read(apiRepositoryProvider).getProfile();
    } catch (_) {}
    state = AuthState(user: user, profile: profile);
    unawaited(_safeRefreshMembership());
  }

  Future<bool> register(String email, String password, String? nickname) async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      if (kIsWeb) {
        await _registerWeb(email, password, nickname);
      } else {
        await _registerNative(email, password, nickname);
      }
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _err(e));
      return false;
    }
  }

  Future<void> _registerNative(
      String email, String password, String? nickname) async {
    final data =
        await _ref.read(apiRepositoryProvider).register(email, password, nickname);
    await _saveAuth(data);
    final user = AppUser.fromJson(data['user']);
    state = AuthState(user: user);
    unawaited(_safeRefreshMembership());
  }

  Future<void> _registerWeb(
      String email, String password, String? nickname) async {
    // 后端 /register 返回 Bearer token 且不下发 cookie；Web 端不复用该 token，
    // 而是紧接着用同一凭据走 web-login 建立 HttpOnly cookie 会话。
    await _ref
        .read(apiRepositoryProvider)
        .register(email, password, nickname);
    await _loginWeb(email, password);
  }

  Future<void> _saveAuth(Map<String, dynamic> data) async {
    final token = data['access_token'] as String;
    _ref.read(tokenStoreProvider).setToken(token);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
  }

  Future<void> saveProfile(UserProfile profile) async {
    final saved = await _ref.read(apiRepositoryProvider).updateProfile(profile);
    state = state.copyWith(profile: saved);
  }

  Future<void> logout() async {
    if (kIsWeb) {
      // 尽力通知后端清 cookie；网络失败也照清前端态。
      try {
        await _ref.read(apiRepositoryProvider).webLogout();
      } catch (_) {}
      final csrfStore = _ref.read(csrfStoreProvider);
      csrfStore.clear();
      csrfStore.sessionActive = false;
    } else {
      _ref.read(tokenStoreProvider).clear();
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_tokenKey);
    }
    _ref.read(membershipProvider.notifier).reset();
    state = const AuthState();
  }

  String _err(Object e) =>
      e is ApiException ? e.message : '操作失败，请重试';
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier(ref);
});
