import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/responsive/breakpoints.dart';
import '../../theme/app_theme.dart';
import 'home_screen.dart';
import 'plan_tab.dart';
import 'profile_tab.dart';

/// 首页导航框架：手机底部 NavigationBar，平板/桌面左侧 NavigationRail。
///
/// 不改动导航信息架构（首页/计划/我的 三个目的地不变），宽屏仅把导航
/// 从底部移到左侧窄栏，并把内容居中限宽，避免超宽屏一行拉太长。
class MainScaffold extends ConsumerStatefulWidget {
  const MainScaffold({super.key});

  @override
  ConsumerState<MainScaffold> createState() => _MainScaffoldState();
}

class _MainScaffoldState extends ConsumerState<MainScaffold> {
  int _index = 0;

  static const _destinations = [
    _NavDest(
      icon: Icons.home_outlined,
      selectedIcon: Icons.home_rounded,
      label: '首页',
    ),
    _NavDest(
      icon: Icons.assignment_outlined,
      selectedIcon: Icons.assignment_rounded,
      label: '计划',
    ),
    _NavDest(
      icon: Icons.person_outline,
      selectedIcon: Icons.person_rounded,
      label: '我的',
    ),
  ];

  final _pages = const [
    HomeScreen(),
    PlanTab(),
    ProfileTab(),
  ];

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final useWideNav = context.useWideNav;
    final content = IndexedStack(index: _index, children: _pages);

    if (useWideNav) {
      return Scaffold(
        body: Row(
          children: [
            _WideNavRail(
              destinations: _destinations,
              index: _index,
              isDark: isDark,
              onSelect: (i) => setState(() => _index = i),
            ),
            const VerticalDivider(width: 1, thickness: 1),
            // 宽屏内容居中限宽；居中元素撑满剩余高度。
            Expanded(
              child: Center(
                child: ConstrainedBox(
                  constraints: BoxConstraints(
                    maxWidth: context.formFactor.contentMaxWidth,
                  ),
                  child: content,
                ),
              ),
            ),
          ],
        ),
      );
    }

    return Scaffold(
      body: content,
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          color: isDark ? AppColors.trainingSurface : Colors.white,
          border: Border(
            top: BorderSide(
              color:
                  isDark ? AppColors.trainingBorder : const Color(0xFFEDEFF2),
            ),
          ),
        ),
        child: SafeArea(
          top: false,
          child: NavigationBar(
            backgroundColor: Colors.transparent,
            elevation: 0,
            height: 62,
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            indicatorColor: AppColors.primary.withValues(alpha: 0.15),
            destinations: [
              for (final d in _destinations)
                NavigationDestination(
                  icon: Icon(d.icon),
                  selectedIcon: Icon(d.selectedIcon, color: AppColors.primary),
                  label: d.label,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavDest {
  final IconData icon;
  final IconData selectedIcon;
  final String label;
  const _NavDest({
    required this.icon,
    required this.selectedIcon,
    required this.label,
  });
}

class _WideNavRail extends StatelessWidget {
  final List<_NavDest> destinations;
  final int index;
  final bool isDark;
  final ValueChanged<int> onSelect;

  const _WideNavRail({
    required this.destinations,
    required this.index,
    required this.isDark,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return NavigationRail(
      backgroundColor:
          isDark ? AppColors.trainingSurface : Colors.white,
      selectedIndex: index,
      onDestinationSelected: onSelect,
      labelType: NavigationRailLabelType.all,
      minWidth: 84,
      useIndicator: true,
      indicatorColor: AppColors.primary.withValues(alpha: 0.15),
      selectedLabelTextStyle: const TextStyle(
        color: AppColors.primary,
        fontSize: 12,
        fontWeight: FontWeight.w700,
      ),
      unselectedLabelTextStyle: TextStyle(
        color: isDark ? AppColors.textMuted : AppColors.textSecondary,
        fontSize: 12,
      ),
      selectedIconTheme: const IconThemeData(color: AppColors.primary),
      unselectedIconTheme: IconThemeData(
        color: isDark ? AppColors.textMuted : AppColors.textSecondary,
      ),
      leading: Padding(
        padding: const EdgeInsets.symmetric(vertical: 18),
        child: Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            gradient: AppColors.energyGradient,
            borderRadius: BorderRadius.circular(14),
            boxShadow: [
              BoxShadow(
                color: AppColors.energy.withValues(alpha: 0.45),
                blurRadius: 18,
                offset: const Offset(0, 4),
              ),
            ],
          ),
          child: const Icon(Icons.bolt_rounded, color: Colors.black, size: 26),
        ),
      ),
      destinations: [
        for (final d in destinations)
          NavigationRailDestination(
            icon: Icon(d.icon),
            selectedIcon: Icon(d.selectedIcon),
            label: Text(d.label),
          ),
      ],
    );
  }
}
