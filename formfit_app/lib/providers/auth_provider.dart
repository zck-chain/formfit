import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/repository.dart';
import '../api/api_client.dart';
import '../models/user.dart';

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

  Future<void> bootstrap() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_tokenKey);
    if (token == null) return;
    _ref.read(tokenStoreProvider).setToken(token);
    try {
      final user = await _fetchMe();
      final profile = await _ref.read(apiRepositoryProvider).getProfile();
      state = AuthState(user: user, profile: profile);
    } catch (_) {
      // token 失效，清理
      await logout();
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
      final data = await _ref.read(apiRepositoryProvider).login(email, password);
      await _saveAuth(data);
      final user = AppUser.fromJson(data['user']);
      UserProfile? profile;
      try {
        profile = await _ref.read(apiRepositoryProvider).getProfile();
      } catch (_) {}
      state = AuthState(user: user, profile: profile);
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _err(e));
      return false;
    }
  }

  Future<bool> register(String email, String password, String? nickname) async {
    state = state.copyWith(isLoading: true, clearError: true);
    try {
      final data =
          await _ref.read(apiRepositoryProvider).register(email, password, nickname);
      await _saveAuth(data);
      final user = AppUser.fromJson(data['user']);
      state = AuthState(user: user);
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: _err(e));
      return false;
    }
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
    _ref.read(tokenStoreProvider).clear();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    state = const AuthState();
  }

  String _err(Object e) =>
      e is ApiException ? e.message : '操作失败，请重试';
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier(ref);
});
