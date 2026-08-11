import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/paywall/paywall_screen.dart';
import '../models/payment.dart';
import '../providers/membership_provider.dart';
import '../theme/app_theme.dart';
import 'cyber/hud_card.dart';

/// 首页免费额度面板：体态评估与 AI 计划生成**共享**同一个月度免费池。
///
/// 展示「本月免费次数 · 剩余 X/limit」一条进度条，下方小字给出各功能已用拆分。
/// PRO 用户显示「不限次」；用尽时进度条高亮并可点击唤起付费墙。
/// 数据来自 `GET /api/membership` 的单个共享 `quota` 对象。
class QuotaPanel extends ConsumerWidget {
  const QuotaPanel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final membership = ref.watch(membershipProvider).valueOrNull;
    // 未登录 / 尚未拉取到会员态时不展示，避免闪烁。
    final quota = membership?.quota;
    if (membership == null || quota == null) {
      return const SizedBox.shrink();
    }
    final isPro = membership.isPro;
    final unlimited = isPro || quota.isUnlimited;
    final exhausted = !unlimited && quota.isExhausted;
    final valueColor = exhausted
        ? AppColors.hot
        : (unlimited ? AppColors.energy : AppColors.cyan);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: GestureDetector(
        onTap: () => PaywallScreen.push<bool>(context, source: '首页额度'),
        behavior: HitTestBehavior.opaque,
        child: HudCard(
          cornerColor: unlimited ? AppColors.energy : AppColors.borderBright,
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
                    unlimited ? '// PRO 不限次' : '// 本月免费次数（评估·计划共享）',
                    style: const TextStyle(
                        fontFamily: 'monospace',
                        color: AppColors.textMuted,
                        fontSize: 11),
                  ),
                  const Spacer(),
                  if (isPro) const _ProPill(),
                ],
              ),
              const SizedBox(height: 14),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    unlimited ? '不限次' : '${quota.remaining}',
                    style: AppTheme.display(26,
                        weight: FontWeight.w800, color: valueColor),
                  ),
                  if (!unlimited) ...[
                    const SizedBox(width: 6),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 5),
                      child: Text(
                        '/ ${quota.limit} 次',
                        style: const TextStyle(
                            fontFamily: 'monospace',
                            color: AppColors.textSecondary,
                            fontSize: 13),
                      ),
                    ),
                  ],
                ],
              ),
              if (!unlimited) ...[
                const SizedBox(height: 4),
                Text(
                  exhausted
                      ? '本月免费次数已用完'
                      : '已用 ${quota.used} 次 · 评估与 AI 计划合计',
                  style: TextStyle(
                    fontFamily: 'monospace',
                    color: exhausted ? AppColors.hot : AppColors.textMuted,
                    fontSize: 11,
                  ),
                ),
                const SizedBox(height: 10),
                ClipRRect(
                  borderRadius: BorderRadius.circular(2),
                  child: LinearProgressIndicator(
                    value: quota.limit > 0
                        ? (quota.used / quota.limit).clamp(0.0, 1.0)
                        : 0.0,
                    minHeight: 5,
                    backgroundColor: AppColors.border,
                    valueColor: AlwaysStoppedAnimation(valueColor),
                  ),
                ),
                if (quota.breakdown.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  _Breakdown(breakdown: quota.breakdown),
                ],
                const SizedBox(height: 12),
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

/// 共享池的各功能已用拆分（仅展示，不暗示独立额度）。
class _Breakdown extends StatelessWidget {
  final Map<String, int> breakdown;
  const _Breakdown({required this.breakdown});

  @override
  Widget build(BuildContext context) {
    final parts = <String>[];
    for (final entry in QuotaFeatures.labels.entries) {
      final used = breakdown[entry.key] ?? 0;
      parts.add('${entry.value} $used 次');
    }
    return Row(
      children: [
        const Icon(Icons.tune_rounded, size: 12, color: AppColors.textMuted),
        const SizedBox(width: 5),
        Expanded(
          child: Text(
            parts.join('  ·  '),
            style: const TextStyle(
                fontFamily: 'monospace',
                color: AppColors.textMuted,
                fontSize: 10),
          ),
        ),
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
