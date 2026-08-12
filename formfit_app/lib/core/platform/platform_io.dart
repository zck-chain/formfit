// 平台判定：native（dart:io）实现。
import 'dart:io' show Platform;

bool isApplePlatform() => Platform.isIOS || Platform.isMacOS;
