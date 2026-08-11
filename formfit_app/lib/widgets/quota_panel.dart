import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/paywall/paywall_screen.dart';
import '../models/payment.dart';
import '../providers/membership_provider.dart';
import '../theme/app_theme.dart';
import 'cyber/hud_card.dart';

/// 首页免费额度面板：展示本月「体态评估 / AI 计划」剩余次数。
///
/// PRO 用户显示「不限次」；免费用户显示 `remaining/limit` 与进度条，
/// 用尽时高亮并可点击唤起付费墙。数据来自 `GET /api/membership` 的 `quota`。
class QuotaPanel extends ConsumerWidget {
  const QuotaPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final membership = ref.watch(membershipProvider).valueOrNull;
    // 未登录 / 尚未拉取到会员态时不展示，避免闪烁。
    if (membership == null) return const SizedBox.shrink();

    final assess = membership.quotaFor(QuotaFeatures.assess);
    final plan = membership.quotaFor(QuotaFeatures.generatePlan);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: GestureDetector(
        onTap: () => PaywallScreen.push<bool>(context, source: '首页额度'),
        behavior: HitTestBehavior.opaque,
        child: HudCard(
          cornerColor:
              membership.isPro ? AppColors.energy : AppColors.borderBright,
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Text('QUOTA',
                      style: TextStyle(
                          fontFamily: 'monospace',
                          color: AppColors.textMuted,
                          fontSize: 11,
                          letterSpacing: 1)),
                  const SizedBox(width: 8),
                  Text(
                    membership.isPro ? '// PRO 不限次' : '// 本月免费额度',
                    style: const TextStyle(
                        fontFamily: 'monospace',
                        color: AppColors.textMuted,
                        fontSize: 11),
                  ),
                  const Spacer(),
                  if (membership.isPro) const _ProPill(),
                ],
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Expanded(
                    child: _QuotaMeter(
                      icon: Icons.camera_alt_rounded,
                      label: QuotaFeatures.labels[QuotaFeatures.assess]!,
                      quota: assess,
                      isPro: membership.isPro,
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: _QuotaMeter(
                      icon: Icons.auto_awesome_rounded,
                      label: QuotaFeatures.labels[QuotaFeatures.generatePlan]!,
                      quota: plan,
                      isPro: membership.isPro,
                    ),
                  ),
                ],
              ),
              if (!membership.isPro) ...[
                const SizedBox(height: 14),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: const [
                    Icon(Icons.bolt_rounded, size: 15, color: AppColors.energy),
                    SizedBox(width: 4),
                    Text('开通 PRO 不限次',
                        style: TextStyle(
                            color: AppColors.energy,
                            fontSize: 12,
                            fontWeight: FontWeight.w700)),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _QuotaMeter extends StatelessWidget {
  final IconData icon;
  final String label;
  final Quota? quota;
  final bool isPro;
  const _QuotaMeter({
    required this.icon,
    required this.label,
    required this.quota,
    required this.isPro,
  });

  @override
  Widget build(BuildContext context) {
    final unlimited = isPro || quota?.isUnlimited == true;
    final exhausted = quota?.isExhausted ?? false;
    final valueColor = exhausted
        ? AppColors.hot
        : (unlimited ? AppColors.energy : AppColors.cyan);
    final used = quota?.used ?? 0;
    final limit = quota?.limit ?? 0;
    final progress = limit > 0 ? (used / limit).clamp(0.0, 1.0) : 0.0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 15, color: AppColors.textSecondary),
            const SizedBox(width: 6),
            Text(label,
                style: const TextStyle(
                    color: AppColors.textSecondary, fontSize: 12)),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          unlimited ? '不限次' : '${quota?.remaining ?? 0} 次',
          style: AppTheme.display(20, weight: FontWeight.w800, color: valueColor),
        ),
        if (!unlimited) ...[
          const SizedBox(height: 2),
          Text('剩余 / 共 $limit 次',
              style: const TextStyle(
                  fontFamily: 'monospace',
                  color: AppColors.textMuted,
                  fontSize: 10)),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 4,
              backgroundColor: AppColors.border,
              valueColor: AlwaysStoppedAnimation(valueColor),
            ),
          ),
        ],
      ],
    );
  }
}

class _ProPill extends StatelessWidget {
  const _ProPill();
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        gradient: AppColors.energyGradient,
        borderRadius: BorderRadius.circular(AppRadius.pill),
      ),
      child: const Text('PRO',
          style: TextStyle(
              color: Colors.black,
              fontSize: 10,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.5)),
    );
  }
}
