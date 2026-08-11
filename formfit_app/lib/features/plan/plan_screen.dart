import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/repository.dart';
import '../../models/plan.dart';
import '../paywall/pro_gate.dart';
import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/exercise_image.dart';
import '../../widgets/safety_notice.dart';

/// 当前活跃计划（内存缓存，进入页面时拉取）
final activePlanProvider =
    StateNotifierProvider<ActivePlanNotifier, AsyncValue<Plan?>>((ref) {
  return ActivePlanNotifier(ref);
});

class ActivePlanNotifier extends StateNotifier<AsyncValue<Plan?>> {
  ActivePlanNotifier(this._ref) : super(const AsyncValue.loading()) {
    load();
  }
  final Ref _ref;

  Future<void> load() async {
    state = const AsyncValue.loading();
    try {
      final plans = await _ref.read(apiRepositoryProvider).listPlans();
      final active = plans.where((p) => p.isActive).firstOrNull ??
          (plans.isNotEmpty ? plans.first : null);
      state = AsyncValue.data(active);
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }

  Future<void> generate() async {
    await runGenerate(_ref.read(apiRepositoryProvider).generatePlan);
  }

  /// 执行一个「生成计划」任务并管理 loading/data/error 状态。
  /// 供付费门控在 402 → 开通后重试时复用同一任务。
  Future<void> runGenerate(Future<Plan> Function() task) async {
    state = const AsyncValue.loading();
    try {
      final plan = await task();
      state = AsyncValue.data(plan);
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }

  /// 把外部（如门控）捕获到的错误写入当前状态以展示错误视图。
  void setError(Object e, StackTrace st) {
    state = AsyncValue.error(e, st);
  }
}

class PlanScreen extends ConsumerWidget {
  const PlanScreen({super.key});

  /// 生成计划，命中 PRO 门控时弹付费墙并在开通后自动重试。
  Future<void> _generateWithGate(BuildContext context, WidgetRef ref) async {
    final notifier = ref.read(activePlanProvider.notifier);
    final repo = ref.read(apiRepositoryProvider);
    try {
      final result = await ProGate.run<Plan>(
        context,
        ref,
        repo.generatePlan,
        source: '生成计划',
      );
      if (result.isSuccess) {
        notifier.runGenerate(() async => result.value!);
      }
    } catch (e, st) {
      notifier.setError(e, st);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final planAsync = ref.watch(activePlanProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('训练计划')),
      body: planAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _error(context, ref, e.toString()),
        data: (plan) {
          if (plan == null) return _empty(context, ref);
          return _planView(context, plan);
        },
      ),
    );
  }

  Widget _planView(BuildContext context, Plan plan) {
    final days = plan.content.days;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // 计划头卡
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            gradient: AppColors.primaryGradient,
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(plan.content.title,
                  style: const TextStyle(
                      color: Colors.black,
                      fontSize: 22,
                      fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Text(
                '${days.length} 天/周 · ${plan.content.weeks} 周 · ${plan.content.goal ?? ''}',
                style: const TextStyle(color: Colors.black87, fontSize: 13),
              ),
              if (plan.content.notes != null) ...[
                const SizedBox(height: 10),
                Text(plan.content.notes!,
                    style: const TextStyle(color: Colors.black54, fontSize: 12)),
              ],
            ],
          ),
        ),
        const SizedBox(height: 20),
        const SafetyNotice(
          level: SafetyNoticeLevel.info,
          message: '训练计划由 AI 根据你的档案生成，仅供健身参考。'
              '请根据自身状态调整强度，训练中如出现头晕、胸闷或急性疼痛请立即停止并就医。',
        ),
        const SizedBox(height: 20),
        const Padding(
          padding: EdgeInsets.only(left: 4, bottom: 8),
          child: Text('训练日',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        ),
        ...days.asMap().entries.map((entry) {
          final i = entry.key;
          final day = entry.value;
          return _DayCard(dayIndex: i, day: day);
        }),
      ],
    );
  }

  Widget _empty(BuildContext context, WidgetRef ref) {
    final hasProfile = ref.watch(authProvider).profile?.goal != null;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.primary.withValues(alpha: .1),
              ),
              child: const Icon(Icons.auto_awesome,
                  size: 40, color: AppColors.primary),
            ),
            const SizedBox(height: 20),
            const Text('生成你的专属计划',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text(
              hasProfile ? 'AI 教练将根据你的档案定制训练计划' : '请先完善身体档案，再生成计划',
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textSecondary),
            ),
            const SizedBox(height: 24),
            if (!hasProfile)
              OutlinedButton(
                onPressed: () => context.push('/profile'),
                child: const Text('去完善档案'),
              ),
            const SizedBox(height: 12),
            ElevatedButton.icon(
              onPressed: () => _generateWithGate(context, ref),
              icon: const Icon(Icons.bolt, color: Colors.black),
              label: const Text('AI 生成计划',
                  style: TextStyle(color: Colors.black)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _error(BuildContext context, WidgetRef ref, String msg) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.error_outline, size: 48, color: AppColors.danger),
          const SizedBox(height: 12),
          Text(msg, textAlign: TextAlign.center),
          const SizedBox(height: 16),
          ElevatedButton(
            onPressed: () => ref.read(activePlanProvider.notifier).load(),
            child: const Text('重试'),
          ),
        ]),
      ),
    );
  }
}

class _DayCard extends StatelessWidget {
  final int dayIndex;
  final PlanDay day;
  const _DayCard({required this.dayIndex, required this.day});

  @override
  Widget build(BuildContext context) {
    final muscles = day.items.map((e) => e.targetZh).whereType<String>().toSet();
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(
            color: Theme.of(context).brightness == Brightness.dark
                ? AppColors.trainingBorder
                : const Color(0xFFEDEFF2)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.md),
        onTap: () => context.push('/plan/$dayIndex'),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              // 日期圆形序号
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: AppColors.primary.withValues(alpha: .12),
                  borderRadius: BorderRadius.circular(12),
                ),
                alignment: Alignment.center,
                child: Text('${dayIndex + 1}',
                    style: const TextStyle(
                        color: AppColors.primary,
                        fontSize: 20,
                        fontWeight: FontWeight.w800)),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(day.dayLabel,
                        style: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text(
                      '${day.focus ?? ''} · ${day.items.length} 个动作',
                      style: const TextStyle(
                          color: AppColors.textSecondary, fontSize: 12),
                    ),
                    if (muscles.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(muscles.take(4).join(' · '),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: AppColors.primary, fontSize: 11)),
                    ],
                  ],
                ),
              ),
              const SizedBox(
                height: 56,
                child: VerticalDivider(width: 20),
              ),
              SizedBox(
                width: 56,
                height: 56,
                child: day.items.isNotEmpty
                    ? ExerciseImage(
                        path: day.items.first.gifUrl,
                        borderRadius: BorderRadius.circular(8),
                      )
                    : null,
              ),
              const SizedBox(width: 4),
              const Icon(Icons.chevron_right, color: AppColors.textMuted),
            ],
          ),
        ),
      ),
    );
  }
}
