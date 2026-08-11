import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:formfit_app/app.dart';

void main() {
  testWidgets('App boots to login and renders brand',
      (WidgetTester tester) async {
    await tester.pumpWidget(const ProviderScope(child: FormFitApp()));
    await tester.pump();

    // 未登录应落在登录页并展示品牌名
    expect(find.text('FormFit'), findsOneWidget);

    // 推进时间，让 flutter_animate 的 Future.delayed(delay) 一次性定时器全部触发
    // （如登录页标题的 delay: 200.ms），否则测试结束时会遗留 pending timer。
    await tester.pump(const Duration(milliseconds: 500));

    // 卸载整棵树，取消 GlowButton 呼吸光 / 粒子背景等 repeat 动画。
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });
}
