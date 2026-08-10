import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../theme/app_theme.dart';
import 'home_screen.dart';
import 'plan_tab.dart';
import 'profile_tab.dart';

/// 首页底部导航框架（Keep 风格）
class MainScaffold extends ConsumerStatefulWidget {
  const MainScaffold({super.key});

  @override
  ConsumerState<MainScaffold> createState() => _MainScaffoldState();
}

class _MainScaffoldState extends ConsumerState<MainScaffold> {
  int _index = 0;

  final _pages = const [
    HomeScreen(),
    PlanTab(),
    ProfileTab(),
  ];

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Scaffold(
      body: IndexedStack(index: _index, children: _pages),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          color: isDark ? AppColors.trainingSurface : Colors.white,
          border: Border(
            top: BorderSide(
              color: isDark ? AppColors.trainingBorder : const Color(0xFFEDEFF2),
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
            destinations: const [
              NavigationDestination(
                icon: Icon(Icons.home_outlined),
                selectedIcon: Icon(Icons.home_rounded, color: AppColors.primary),
                label: '首页',
              ),
              NavigationDestination(
                icon: Icon(Icons.assignment_outlined),
                selectedIcon:
                    Icon(Icons.assignment_rounded, color: AppColors.primary),
                label: '计划',
              ),
              NavigationDestination(
                icon: Icon(Icons.person_outline),
                selectedIcon:
                    Icon(Icons.person_rounded, color: AppColors.primary),
                label: '我的',
              ),
            ],
          ),
        ),
      ),
    );
  }
}
