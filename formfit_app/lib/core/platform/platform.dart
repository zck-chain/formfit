/// 平台判定入口。
///
/// 用条件导入把 `dart:io` 的 `Platform` 收敛到 native 实现，
/// 使 Web 构建树不直接引用 `Platform`（在 Web 上 `Platform.isIOS`
/// 这类顶层 getter 会抛异常）。
///
/// Web 走 [platform_web.dart] 恒返回 false；native 走
/// [platform_io.dart] 用 `dart:io` 判断 iOS/macOS。
library;

export 'platform_web.dart' if (dart.library.io) 'platform_io.dart';
