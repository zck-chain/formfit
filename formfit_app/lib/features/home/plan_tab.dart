import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/repository.dart';
import '../../core/responsive/breakpoints.dart';
import '../../models/plan.dart';
import '../../theme/app_theme.dart';
import '../../widgets/exercise_image.dart';

final plansProvider = FutureProvider.autoDispose((ref) async {
  return ref.watch(apiRepositoryProvider).listPlans();
});

class PlanTab extends ConsumerWidget {
  const PlanTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final plans = ref.watch(plansProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('我的计划')),
      body: Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxWidth: context.formFactor.contentMaxWidth,
          ),
          child: RefreshIndicator(
            onRefresh: () async => ref.invalidate(plansProvider),
            child: plans.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => _error(context, ref, e.toString()),
              data: (list) {
                if (list.isEmpty) return _empty(context);
                return ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: list.length,
                  itemBuilder: (_, i) => _PlanCard(plan: list[i]),
                );
              },
            ),
          ),
        ),
      ),
    );
  }

  Widget _empty(BuildContext context) {
    return ListView(
      children: [
        const SizedBox(height: 80),
        const Icon(Icons.assignment_outlined, size: 64, color: AppColors.textMuted),
        const SizedBox(height: 16),
        const Center(
          child: Text('还没有训练计划',
              style: TextStyle(fontSize: 16, color: AppColors.textSecondary)),
        ),
        const SizedBox(height: 24),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 40),
          child: ElevatedButton.icon(
            onPressed: () => context.push('/plan'),
            icon: const Icon(Icons.auto_awesome, color: Colors.black),
            label: const Text('AI 生成计划', style: TextStyle(color: Colors.black)),
          ),
        ),
      ],
    );
  }

  Widget _error(BuildContext context, WidgetRef ref, String msg) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.cloud_off, size: 48, color: AppColors.textMuted),
          const SizedBox(height: 12),
          Text(msg, textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textSecondary)),
          const SizedBox(height: 16),
          OutlinedButton(
            onPressed: () => ref.invalidate(plansProvider),
            child: const Text('重试'),
          ),
        ]),
      ),
    );
  }
}

class _PlanCard extends StatelessWidget {
  final Plan plan;
  const _PlanCard({required this.plan});

  @override
  Widget build(BuildContext context) {
    final days = plan.content.days;
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
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
        onTap: () => context.push('/plan'),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(plan.content.title,
                        style: const TextStyle(
                            fontSize: 17, fontWeight: FontWeight.w700)),
                  ),
                  if (plan.isActive)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: AppColors.primary.withValues(alpha: .12),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: const Text('进行中',
                          style: TextStyle(
                              color: AppColors.primary,
                              fontSize: 12,
                              fontWeight: FontWeight.w600)),
                    ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                '${days.length} 天/周 · ${plan.content.weeks} 周 · ${plan.content.goal ?? ''}',
                style: const TextStyle(
                    color: AppColors.textSecondary, fontSize: 13),
              ),
              const SizedBox(height: 12),
              SizedBox(
                height: 56,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: days.length.clamp(0, 7),
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, i) {
                    final item = days[i].items.isNotEmpty
                        ? days[i].items.first
                        : null;
                    return ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: item != null
                          ? ExerciseImage(path: item.gifUrl, size: 56)
                          : Container(
                              width: 56,
                              height: 56,
                              color: AppColors.bg,
                            ),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
