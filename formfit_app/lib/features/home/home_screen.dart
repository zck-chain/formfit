import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/repository.dart';
import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/badges.dart';

/// 最新计划 Provider（简单缓存）
final latestPlanProvider = FutureProvider.autoDispose((ref) async {
  final plans = await ref.watch(apiRepositoryProvider).listPlans();
  return plans;
});

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final user = auth.user;
    final profile = auth.profile;
    final greeting = _greeting();

    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(latestPlanProvider);
            try {
              final p = await ref.read(apiRepositoryProvider).getProfile();
              ref.read(authProvider.notifier).saveProfile(p);
            } catch (_) {}
          },
          child: ListView(
            padding: const EdgeInsets.only(bottom: 32),
            children: [
              const SizedBox(height: 8),
              // 顶部问候 + 头像
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(greeting,
                              style: const TextStyle(
                                  color: AppColors.textSecondary, fontSize: 14)),
                          const SizedBox(height: 2),
                          Text(
                            user?.nickname ?? user?.email.split('@').first ?? '训练者',
                            style: const TextStyle(
                                fontSize: 24, fontWeight: FontWeight.w800),
                          ),
                        ],
                      ),
                    ),
                    CircleAvatar(
                      radius: 24,
                      backgroundColor: AppColors.primary.withValues(alpha: 0.15),
                      child: Text(
                        (user?.nickname ?? user?.email ?? 'U')
                            .substring(0, 1)
                            .toUpperCase(),
                        style: const TextStyle(
                            color: AppColors.primary, fontWeight: FontWeight.w700),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 22),

              // 英雄卡：今日状态
              _HeroCard(
                hasProfile: profile != null && profile.goal != null,
                goal: profile?.goal,
                direction: profile?.goal,
                bmi: profile?.bmi,
              ),
              const SizedBox(height: 18),

              // 快捷入口
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: Row(
                  children: [
                    Expanded(
                      child: _QuickAction(
                        icon: Icons.camera_alt_rounded,
                        label: '体态评估',
                        sub: '拍照分析',
                        gradient: const LinearGradient(
                          colors: [Color(0xFF2BE6A6), Color(0xFF00B87A)],
                        ),
                        onTap: () => context.push('/assessment'),
                      ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: _QuickAction(
                        icon: Icons.auto_awesome_rounded,
                        label: '生成计划',
                        sub: 'AI 私教定制',
                        gradient: const LinearGradient(
                          colors: [Color(0xFFFF9A6B), Color(0xFFFF6B45)],
                        ),
                        onTap: () => context.push('/plan'),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),

              // 数据概览标题
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 20),
                child: Text('训练概览',
                    style:
                        TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              ),
              const SizedBox(height: 12),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: _StatsRow(profile: profile),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _greeting() {
    final h = DateTime.now().hour;
    if (h < 6) return '夜深了';
    if (h < 11) return '早上好';
    if (h < 14) return '中午好';
    if (h < 18) return '下午好';
    return '晚上好';
  }
}

class _HeroCard extends StatelessWidget {
  final bool hasProfile;
  final String? goal;
  final String? direction;
  final double? bmi;
  const _HeroCard({
    required this.hasProfile,
    this.goal,
    this.direction,
    this.bmi,
  });

  @override
  Widget build(BuildContext context) {
    return Container(      margin: const EdgeInsets.symmetric(horizontal: 20),
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF0E1114), Color(0xFF1F2A30)],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.bolt_rounded, color: AppColors.primary, size: 20),
              const SizedBox(width: 6),
              const Text(
                '今日状态',
                style: TextStyle(
                    color: Colors.white70,
                    fontSize: 13,
                    fontWeight: FontWeight.w500),
              ),
              const Spacer(),
              if (hasProfile) DirectionBadge(direction: _dirKey(goal)),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            hasProfile ? '目标：${goal ?? '未设置'}' : '先完成身体档案，让 AI 更懂你',
            style: const TextStyle(
                color: Colors.white,
                fontSize: 22,
                fontWeight: FontWeight.w800,
                height: 1.3),
          ),
          const SizedBox(height: 6),
          Text(
            hasProfile
                ? '每周训练 ${'自动安排'} · BMI ${bmi?.toStringAsFixed(1) ?? '—'}'
                : '填写身高体重与目标，即可生成专属计划',
            style: const TextStyle(color: Colors.white54, fontSize: 13),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: () {
                GoRouter.of(context).push(hasProfile ? '/plan' : '/profile');
              },
              icon: Icon(hasProfile ? Icons.play_arrow_rounded : Icons.arrow_forward,
                  color: Colors.black),
              label: Text(hasProfile ? '开始今日训练' : '去完善档案',
                  style: const TextStyle(color: Colors.black)),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primary,
                minimumSize: const Size(double.infinity, 48),
              ),
            ),
          ),
        ],
      ),
    );
  }

  // 把中文目标映射成方向 key
  String _dirKey(String? goal) {
    if (goal == null) return 'maintain';
    if (goal.contains('增肌')) return 'gain';
    if (goal.contains('减脂') || goal.contains('减重')) return 'fat_loss';
    if (goal.contains('康复') || goal.contains('伤')) return 'rehab';
    return 'maintain';
  }

  // 方便在非 context 方法里跳转
  BuildContext context(BuildContext c) => c;
}

class _QuickAction extends StatelessWidget {
  final IconData icon;
  final String label;
  final String sub;
  final Gradient gradient;
  final VoidCallback onTap;
  const _QuickAction({
    required this.icon,
    required this.label,
    required this.sub,
    required this.gradient,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.md),
        onTap: onTap,
        child: Ink(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.md),
            color: Theme.of(context).cardColor,
            border: Border.all(
                color: Theme.of(context).brightness == Brightness.dark
                    ? AppColors.trainingBorder
                    : const Color(0xFFEDEFF2)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  gradient: gradient,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: Colors.white, size: 22),
              ),
              const SizedBox(height: 12),
              Text(label,
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w700)),
              const SizedBox(height: 2),
              Text(sub,
                  style: const TextStyle(
                      color: AppColors.textSecondary, fontSize: 12)),
            ],
          ),
        ),
      ),
    );
  }
}

class _StatsRow extends StatelessWidget {
  final dynamic profile;
  const _StatsRow({this.profile});
  @override
  Widget build(BuildContext context) {
    final items = [
      ('体重', profile?.weightKg != null ? '${profile.weightKg!.toStringAsFixed(0)}kg' : '—'),
      ('身高', profile?.heightCm != null ? '${profile.heightCm!.toStringAsFixed(0)}cm' : '—'),
      ('BMI', profile?.bmi != null ? profile.bmi!.toStringAsFixed(1) : '—'),
      ('周练', '${profile?.daysPerWeek ?? '—'}天'),
    ];
    return Row(
      children: [
        for (final (label, value) in items) ...[
          Expanded(child: _StatCell(label: label, value: value)),
          if (label != items.last.$1) const SizedBox(width: 10),
        ]
      ],
    );
  }
}

class _StatCell extends StatelessWidget {
  final String label;
  final String value;
  const _StatCell({required this.label, required this.value});
  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 14),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(
            color: isDark ? AppColors.trainingBorder : const Color(0xFFEDEFF2)),
      ),
      child: Column(
        children: [
          Text(value,
              style: const TextStyle(
                  fontSize: 20, fontWeight: FontWeight.w800)),
          const SizedBox(height: 2),
          Text(label,
              style: const TextStyle(
                  color: AppColors.textSecondary, fontSize: 12)),
        ],
      ),
    );
  }
}
