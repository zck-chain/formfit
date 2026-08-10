import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/repository.dart';
import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/cyber/cyber_background.dart';
import '../../widgets/cyber/glow_button.dart';
import '../../widgets/cyber/hud_card.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final user = auth.user;
    final profile = auth.profile;
    final name = user?.nickname ?? user?.email.split('@').first ?? '训练者';

    return Scaffold(
      body: CyberBackground(
        child: SafeArea(
          child: RefreshIndicator(
            color: AppColors.energy,
            backgroundColor: AppColors.card,
            onRefresh: () async {
              // 计划列表由 PlanTab.plansProvider（autoDispose）在切回时自行刷新；
              // 这里只刷新用户档案。
              try {
                final p = await ref.read(apiRepositoryProvider).getProfile();
                ref.read(authProvider.notifier).saveProfile(p);
              } catch (_) {}
            },
            child: ListView(
              padding: const EdgeInsets.only(bottom: 32),
              children: [
                const SizedBox(height: 12),
                _topBar(name),
                const SizedBox(height: 22),
                _heroCard(profile, context),
                const SizedBox(height: 18),
                _quickActions(context),
                const SizedBox(height: 26),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Row(
                    children: [
                      Text('TRAINING',
                          style: AppTheme.display(18, weight: FontWeight.w800)),
                      const SizedBox(width: 8),
                      const Text('// 数据',
                          style: TextStyle(
                              fontFamily: 'monospace',
                              color: AppColors.textMuted,
                              fontSize: 12)),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                _stats(profile),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _topBar(String name) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('> SYSTEM ONLINE',
                    style: TextStyle(
                        fontFamily: 'monospace',
                        color: AppColors.energy,
                        fontSize: 11,
                        letterSpacing: 1)),
                const SizedBox(height: 4),
                Text('$name 🔥',
                    style: AppTheme.display(24, weight: FontWeight.w800)),
              ],
            ),
          ),
          Container(
            width: 46, height: 46,
            decoration: BoxDecoration(
              gradient: AppColors.energyGradient,
              borderRadius: BorderRadius.circular(14),
              boxShadow: [
                BoxShadow(
                    color: AppColors.energy.withValues(alpha: 0.5),
                    blurRadius: 18,
                    offset: const Offset(0, 4)),
              ],
            ),
            child: const Icon(Icons.person, color: Colors.black, size: 22),
          ),
        ],
      ),
    );
  }

  Widget _heroCard(profile, BuildContext context) {
    final hasGoal = profile?.goal != null;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: HudCard(
        cornerColor: AppColors.energy,
        glow: true,
        padding: const EdgeInsets.all(22),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                DataTag(
                  label: 'GOAL',
                  value: hasGoal ? profile.goal : 'UNSET',
                  color: hasGoal ? AppColors.energy : AppColors.textMuted,
                ),
                const Spacer(),
                const Icon(Icons.bolt_rounded,
                    color: AppColors.energy, size: 20),
              ],
            ),
            const SizedBox(height: 18),
            Text(
              hasGoal ? '今日也要练爆，冲！' : '先完成档案，启动 AI 私教',
              style: AppTheme.display(24, weight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            Text(
              hasGoal
                  ? '已定制 ${profile.daysPerWeek ?? 3} 天/周训练协议'
                  : '填写身体数据与目标，生成专属计划',
              style: const TextStyle(
                  fontFamily: 'monospace',
                  color: AppColors.textSecondary,
                  fontSize: 12),
            ),
            const SizedBox(height: 20),
            GlowButton(
              label: hasGoal ? '开始今日训练' : '去完善档案',
              icon: Icons.play_arrow_rounded,
              height: 50,
              onTap: () => context.push(hasGoal ? '/plan' : '/profile'),
            ),
          ],
        ),
      ),
    ).animate().fadeIn().slideY(begin: 0.08);
  }

  Widget _quickActions(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Row(
        children: [
          Expanded(
            child: _actionCard(
              context,
              label: '体态评估',
              code: 'SCAN',
              icon: Icons.camera_alt_rounded,
              gradient: AppColors.hotGradient,
              color: AppColors.hot,
              onTap: () => context.push('/assessment'),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: _actionCard(
              context,
              label: 'AI 计划',
              code: 'GEN',
              icon: Icons.auto_awesome_rounded,
              gradient: AppColors.cyanGradient,
              color: AppColors.cyan,
              onTap: () => context.push('/plan'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _actionCard(
    BuildContext context, {
    required String label,
    required String code,
    required IconData icon,
    required Gradient gradient,
    required Color color,
    required VoidCallback onTap,
  }) {
    return HudCard(
      cornerColor: color,
      padding: const EdgeInsets.all(16),
      child: GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.all(11),
              decoration: BoxDecoration(
                gradient: gradient,
                borderRadius: BorderRadius.circular(12),
                boxShadow: [
                  BoxShadow(
                      color: color.withValues(alpha: 0.4), blurRadius: 14),
                ],
              ),
              child: Icon(icon, color: Colors.white, size: 22),
            ),
            const SizedBox(height: 14),
            Text(label,
                style: AppTheme.display(15, weight: FontWeight.w700)),
            const SizedBox(height: 2),
            Text('// $code',
                style: const TextStyle(
                    fontFamily: 'monospace',
                    color: AppColors.textMuted,
                    fontSize: 11)),
          ],
        ),
      ),
    );
  }

  Widget _stats(profile) {
    final items = [
      (
        'WEIGHT',
        profile?.weightKg != null
            ? '${profile.weightKg!.toStringAsFixed(0)}kg'
            : '—'
      ),
      (
        'HEIGHT',
        profile?.heightCm != null
            ? '${profile.heightCm!.toStringAsFixed(0)}cm'
            : '—'
      ),
      ('BMI', profile?.bmi != null ? profile.bmi!.toStringAsFixed(1) : '—'),
      ('DAYS', '${profile?.daysPerWeek ?? '—'}d'),
    ];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Row(
        children: [
          for (var i = 0; i < items.length; i++) ...[
            Expanded(
                child: _statCell(items[i].$1, items[i].$2,
                    highlight: i == 2)),
            if (i < items.length - 1) const SizedBox(width: 10),
          ]
        ],
      ),
    );
  }

  Widget _statCell(String label, String value, {bool highlight = false}) {
    return HudCard(
      cornerColor: highlight ? AppColors.cyan : AppColors.borderBright,
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Column(
        children: [
          Text(value,
              style: AppTheme.display(20,
                  weight: FontWeight.w800,
                  color: highlight ? AppColors.cyan : AppColors.textPrimary)),
          const SizedBox(height: 6),
          Text(label,
              style: const TextStyle(
                  fontFamily: 'monospace',
                  color: AppColors.textMuted,
                  fontSize: 10,
                  letterSpacing: 0.5)),
        ],
      ),
    );
  }
}
