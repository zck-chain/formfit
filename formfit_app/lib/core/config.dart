/// 应用配置
class AppConfig {
  AppConfig._();

  /// 后端地址。
  /// - iOS 模拟器访问宿主机用 127.0.0.1
  /// - Android 模拟器访问宿主机用 10.0.2.2
  /// - 真机组网调试时改成你电脑的局域网 IP，例如 192.168.x.x
  /// 构建时可用 --dart-define=API_BASE_URL=http://x.x.x.x:8000 覆盖
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  /// 后端返回的媒体路径形如 "/media/exercises/videos/xxx.gif"，
  /// 这里拼上 host 得到完整可访问 URL。
  static String resolveUrl(String? path) {
    if (path == null || path.isEmpty) return '';
    if (path.startsWith('http://') || path.startsWith('https://')) {
      return path;
    }
    final base = apiBaseUrl.endsWith('/')
        ? apiBaseUrl.substring(0, apiBaseUrl.length - 1)
        : apiBaseUrl;
    final p = path.startsWith('/') ? path : '/$path';
    return '$base$p';
  }
}
