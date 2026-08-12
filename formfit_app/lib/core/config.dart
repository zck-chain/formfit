/// 应用配置
class AppConfig {
  AppConfig._();

  /// 后端地址。
  /// - iOS 模拟器访问宿主机用 127.0.0.1
  /// - Android 模拟器访问宿主机用 10.0.2.2
  /// - 真机组网调试时改成你电脑的局域网 IP，例如 192.168.x.x
  ///
  /// 构建时通过 `--dart-define=API_BASE_URL=...` 覆盖。
  ///
  /// ### Web 同源部署
  /// Web 生产环境通常前后端同源，应传空串让 Dio 使用相对路径：
  /// ```
  /// flutter build web --dart-define=API_BASE_URL=
  /// ```
  /// 也可传同域 origin（如 `https://app.example.com`），二者等价。
  /// 开发期（`flutter run -d chrome`）默认指向 `http://127.0.0.1:8000`，
  /// 并依赖后端 CORS 放行。
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  /// 是否使用相对路径（同源部署）。为空时 Dio 的 baseUrl 为空，
  /// 请求 `/api/...` 会落到当前页面 origin。
  static bool get usesRelativeApi => apiBaseUrl.isEmpty;

  /// 后端返回的媒体路径形如 "/media/exercises/videos/xxx.gif"，
  /// 这里拼上 host 得到完整可访问 URL。同源部署时直接返回相对路径，
  /// 由浏览器自行解析到当前 origin。
  static String resolveUrl(String? path) {
    if (path == null || path.isEmpty) return '';
    if (path.startsWith('http://') || path.startsWith('https://')) {
      return path;
    }
    if (usesRelativeApi) {
      return path.startsWith('/') ? path : '/$path';
    }
    final base = apiBaseUrl.endsWith('/')
        ? apiBaseUrl.substring(0, apiBaseUrl.length - 1)
        : apiBaseUrl;
    final p = path.startsWith('/') ? path : '/$path';
    return '$base$p';
  }
}
