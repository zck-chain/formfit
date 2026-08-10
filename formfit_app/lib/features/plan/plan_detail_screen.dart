import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../models/plan.dart';
import '../../theme/app_theme.dart';
import '../../widgets/exercise_image.dart';
import 'plan_screen.dart';

/// 单日训练动作列表
class PlanDayScreen extends ConsumerWidget {
  final int dayIndex;
  const PlanDayScreen({super.key, required this.dayIndex});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final planAsync = ref.watch(activePlanProvider);
    final days = planAsync.value?.content.days;
    final dayLabel = days != null && dayIndex >= 0 && dayIndex < days.length
        ? days[dayIndex].dayLabel
        : '训练日';
    return Scaffold(
      appBar: AppBar(title: Text(dayLabel)),
      body: planAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('加载失败：$e')),
        data: (plan) {
          if (plan == null) {
            return const Center(child: Text('暂无计划'));
          }
          final days = plan.content.days;
          if (dayIndex < 0 || dayIndex >= days.length) {
            return const Center(child: Text('该训练日不存在'));
          }
          final day = days[dayIndex];
          return Column(
            children: [
              Expanded(
                child: day.items.isEmpty
                    ? const Center(
                        child: Text('这一天还没有安排动作',
                            style:
                                TextStyle(color: AppColors.textSecondary)))
                    : ListView.separated(
                        padding: const EdgeInsets.all(16),
                        itemCount: day.items.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 10),
                        itemBuilder: (_, i) => _ExerciseTile(
                          index: i,
                          item: day.items[i],
                        ),
                      ),
              ),
              _startBar(context, day),
            ],
          );
        },
      ),
    );
  }

  Widget _startBar(BuildContext context, PlanDay day) {
    final canStart = day.items.isNotEmpty;
    return SafeArea(
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Theme.of(context).cardColor,
          border: const Border(top: BorderSide(color: Color(0xFFEDEFF2))),
        ),
        child: ElevatedButton.icon(
          onPressed: canStart ? () => context.push('/workout/$dayIndex') : null,
          icon: const Icon(Icons.play_arrow_rounded, color: Colors.black, size: 22),
          label: Text(canStart ? '开始训练 · ${day.items.length} 个动作' : '暂无可训练动作',
              style: const TextStyle(color: Colors.black)),
        ),
      ),
    );
  }
}

class _ExerciseTile extends StatelessWidget {
  final int index;
  final PlanItem item;
  const _ExerciseTile({required this.index, required this.item});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(
            color: isDark ? AppColors.trainingBorder : const Color(0xFFEDEFF2)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            ExerciseImage(
              path: item.gifUrl,
              size: 64,
              borderRadius: BorderRadius.circular(10),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.name,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 15, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    children: [
                      _miniTag(item.targetZh ?? ''),
                      if (item.equipmentZh != null && item.equipmentZh!.isNotEmpty)
                        _miniTag(item.equipmentZh!, muted: true),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '${item.sets} 组 × ${item.reps}'
                    '${item.restSec != null ? '  ·  休息 ${item.restSec}s' : ''}',
                    style: const TextStyle(
                        color: AppColors.primary,
                        fontSize: 13,
                        fontWeight: FontWeight.w700),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: AppColors.textMuted),
          ],
        ),
      ),
    );
  }

  Widget _miniTag(String text, {bool muted = false}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: muted
            ? AppColors.textMuted.withValues(alpha: .12)
            : AppColors.primary.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 11,
          color: muted ? AppColors.textSecondary : AppColors.primary,
          fontWeight: FontWeight.w500,
        ),
      ),
    );
  }
}
