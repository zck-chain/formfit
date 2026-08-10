import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'features/assessment/assessment_screen.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/register_screen.dart';
import 'features/home/main_scaffold.dart';
import 'features/plan/plan_detail_screen.dart';
import 'features/plan/plan_screen.dart';
import 'features/profile/profile_screen.dart';
import 'features/workout/workout_screen.dart';
import 'providers/auth_provider.dart';
import 'theme/app_theme.dart';

final _router = GoRouter(
  initialLocation: '/',
  redirect: (context, state) {
    final container = ProviderScope.containerOf(context, listen: false);
    final loggedIn = container.read(authProvider).isLoggedIn;
    final loc = state.matchedLocation;
    final loggingIn = loc == '/login' || loc == '/register';
    if (!loggedIn && !loggingIn) return '/login';
    if (loggedIn && loggingIn) return '/';
    return null;
  },
  routes: [
    GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
    GoRoute(path: '/register', builder: (_, __) => const RegisterScreen()),
    GoRoute(path: '/', builder: (_, __) => const MainScaffold()),
    GoRoute(path: '/profile', builder: (_, __) => const ProfileScreen()),
    GoRoute(path: '/assessment', builder: (_, __) => const AssessmentScreen()),
    GoRoute(path: '/plan', builder: (_, __) => const PlanScreen()),
    GoRoute(
      path: '/plan/:dayIndex',
      builder: (_, s) =>
          PlanDayScreen(dayIndex: int.parse(s.pathParameters['dayIndex']!)),
    ),
    GoRoute(
      path: '/workout/:dayIndex',
      builder: (_, s) =>
          WorkoutScreen(dayIndex: int.parse(s.pathParameters['dayIndex']!)),
    ),
  ],
);

class FormFitApp extends ConsumerWidget {
  const FormFitApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // 登录态变化时刷新路由（触发 redirect）
    ref.listen(authProvider, (_, __) => _router.refresh());

    return MaterialApp.router(
      title: 'FormFit',
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.system,
      debugShowCheckedModeBanner: false,
      routerConfig: _router,
    );
  }
}
