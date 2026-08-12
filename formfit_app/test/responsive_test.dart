import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:formfit_app/api/repository.dart';
import 'package:formfit_app/core/responsive/breakpoints.dart';
import 'package:formfit_app/features/home/main_scaffold.dart';
import 'package:formfit_app/models/plan.dart';

import 'fakes/fake_api_repository.dart';

/// 空计划列表的假仓储，避免 plansProvider 打真实网络。
class _OfflineRepo extends FakeApiRepository {
  _OfflineRepo() : super();
  @override
  Future<List<Plan>> listPlans() async => const [];
}

extension on WidgetTester {
  Future<void> flush([int frames = 10]) async {
    for (var i = 0; i < frames; i++) {
      await pump(const Duration(milliseconds: 50));
    }
  }
}

void main() {
  group('断点判定（最短边）', () {
    testWidgets('375 宽度 → phone', (tester) async {
      tester.view.physicalSize = const Size(375, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      late FormFactor factor;
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(builder: (context) {
            factor = context.formFactor;
            return const SizedBox();
          }),
        ),
      );
      expect(factor, FormFactor.phone);
    });

    testWidgets('768 宽度 → tablet', (tester) async {
      tester.view.physicalSize = const Size(768, 1024);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      late FormFactor factor;
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(builder: (context) {
            factor = context.formFactor;
            return const SizedBox();
          }),
        ),
      );
      expect(factor, FormFactor.tablet);
    });

    testWidgets('1280 宽度（1280×1024）→ desktop', (tester) async {
      tester.view.physicalSize = const Size(1280, 1024);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      late FormFactor factor;
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(builder: (context) {
            factor = context.formFactor;
            return const SizedBox();
          }),
        ),
      );
      expect(factor, FormFactor.desktop);
    });

    testWidgets('横屏手机（667×375，最短边 375）仍判定为 phone', (tester) async {
      tester.view.physicalSize = const Size(667, 375);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      late FormFactor factor;
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(builder: (context) {
            factor = context.formFactor;
            return const SizedBox();
          }),
        ),
      );
      expect(factor, FormFactor.phone);
    });
  });

  group('主框架导航随断点切换', () {
    Widget scaffold() {
      return UncontrolledProviderScope(
        container: ProviderContainer(overrides: [
          apiRepositoryProvider.overrideWithValue(_OfflineRepo()),
        ]),
        child: const MaterialApp(home: MainScaffold()),
      );
    }

    testWidgets('窄屏使用底部 NavigationBar，不显示 NavigationRail',
        (tester) async {
      tester.view.physicalSize = const Size(375, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(scaffold());
      await tester.flush();

      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.byType(NavigationRail), findsNothing);

      // 卸载树，取消无限呼吸/粒子动画，避免遗留 pending timer。
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
    });

    testWidgets('宽屏（1440×1080）使用左侧 NavigationRail，内容居中限宽',
        (tester) async {
      tester.view.physicalSize = const Size(1440, 1080);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(scaffold());
      await tester.flush();

      expect(find.byType(NavigationRail), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing);

      // 桌面档内容最大宽度 900，应有一个 ConstrainedBox 生效。
      final constrainedBox = tester.widget<ConstrainedBox>(
        find.byWidgetPredicate(
          (w) =>
              w is ConstrainedBox &&
              w.constraints.maxWidth == Breakpoints.desktopContentMaxWidth,
        ),
      );
      expect(constrainedBox.constraints.maxWidth,
          Breakpoints.desktopContentMaxWidth);

      // 卸载树，取消无限呼吸/粒子动画，避免遗留 pending timer。
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
    });
  });
}
