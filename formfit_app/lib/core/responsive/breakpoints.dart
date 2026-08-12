import 'package:flutter/widgets.dart';

/// 响应式断点（移动优先）。
///
/// - [phone]   < 600  ：单列、底部导航（手机竖/横屏）。
/// - [tablet]  600–1024：内容居中限宽，宽屏导航栏。
/// - [desktop] > 1024 ：内容居中限宽，左侧导航栏。
///
/// 以最短边（[MediaQueryData.size] 的最短边）判定档位，
/// 这样横屏手机不会被误判为平板/桌面。
class Breakpoints {
  Breakpoints._();

  static const double phoneMax = 600;
  static const double tabletMax = 1024;

  /// 手机单列内容内边距。
  static const double phonePadding = 16;

  /// 平板/桌面内容居中最大宽度。
  static const double tabletContentMaxWidth = 720;
  static const double desktopContentMaxWidth = 900;

  /// 表单类页面（登录/注册/档案编辑）在大屏上的最大宽度。
  static const double formMaxWidth = 520;

  /// 评估图片预览在大屏下的最大高度。
  static const double assessmentImageMaxHeight = 420;
}

enum FormFactor { phone, tablet, desktop }

extension FormFactorX on FormFactor {
  bool get isPhone => this == FormFactor.phone;
  bool get isTablet => this == FormFactor.tablet;
  bool get isDesktop => this == FormFactor.desktop;

  /// 该档位下主流程内容居中最大宽度；手机返回无限宽（撑满）。
  double get contentMaxWidth {
    switch (this) {
      case FormFactor.phone:
        return double.infinity;
      case FormFactor.tablet:
        return Breakpoints.tabletContentMaxWidth;
      case FormFactor.desktop:
        return Breakpoints.desktopContentMaxWidth;
    }
  }
}

/// 读取当前 [FormFactor] 的便捷扩展。
extension ResponsiveContext on BuildContext {
  FormFactor get formFactor {
    // 用最短边判定，横屏手机仍归为 phone；只用 sizeOf 避免无关字段重建。
    final shortestSide = MediaQuery.sizeOf(this).shortestSide;
    if (shortestSide >= Breakpoints.tabletMax) return FormFactor.desktop;
    if (shortestSide >= Breakpoints.phoneMax) return FormFactor.tablet;
    return FormFactor.phone;
  }

  bool get isPhone => formFactor.isPhone;
  bool get isTablet => formFactor.isTablet;
  bool get isDesktop => formFactor.isDesktop;

  /// 宽屏（平板及以上）时使用左侧导航栏，否则用底部导航。
  bool get useWideNav => formFactor != FormFactor.phone;
}
