import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/repository.dart';
import '../../models/plan.dart';
import '../../theme/app_theme.dart';
import '../../widgets/exercise_image.dart';
import '../plan/plan_screen.dart';

/// 跟练页：逐个动作完成训练，结束后保存记录
class WorkoutScreen extends ConsumerStatefulWidget {
  final int dayIndex;
  const WorkoutScreen({super.key, required this.dayIndex});

  @override
  ConsumerState<WorkoutScreen> createState() => _WorkoutScreenState();
}

class _WorkoutScreenState extends ConsumerState<WorkoutScreen> {
  int _current = 0;
  late List<_SetLog> _logs;
  bool _logsReady = false;
  final _weightCtrl = TextEditingController();
  final _repsCtrl = TextEditingController();
  bool _finished = false;
  bool _saving = false;

  @override
  void dispose() {
    _weightCtrl.dispose();
    _repsCtrl.dispose();
    super.dispose();
  }

  PlanDay get _day {
    final plan = ref.read(activePlanProvider).value;
    return plan!.content.days[widget.dayIndex];
  }

  PlanItem get _item => _day.items[_current];

  void _initLogs() {
    _logs = List.generate(
      _day.items.length,
      (i) => _SetLog(exerciseId: _day.items[i].exerciseId),
    );
    _prefill();
  }

  void _prefill() {
    final item = _item;
    final log = _logs[_current];
    log.sets = item.sets;
    log.reps = int.tryParse(item.reps.split('-').first) ?? 10;
    _weightCtrl.text = log.weight?.toStringAsFixed(0) ?? '';
    _repsCtrl.text = log.reps?.toString() ?? '';
  }

  Future<void> _finish() async {
    setState(() => _saving = true);
    try {
      final sets = _logs
          .map((l) => {
                'exercise_id': l.exerciseId,
                'set_index': 1,
                'weight_kg': l.weight,
                'reps': l.reps,
                'done': true,
              })
          .toList();
      await ref.read(apiRepositoryProvider).saveWorkoutLog(
            title: _day.dayLabel,
            durationMin: 30,
            sets: sets,
          );
      if (!mounted) return;
      setState(() => _finished = true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('保存失败：$e')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final plan = ref.watch(activePlanProvider);
    return plan.when(
      loading: () => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      ),
      error: (e, _) => Scaffold(body: Center(child: Text('$e'))),
      data: (p) {
        if (!_logsReady) {
          _initLogs();
          _logsReady = true;
        }
        if (_finished) return _finishView();
        return _workoutView();
      },
    );
  }

  Widget _workoutView() {
    final item = _item;
    final total = _day.items.length;
    final progress = (_current + 1) / total;

    return Theme(
      data: AppTheme.dark,
      child: Scaffold(
        backgroundColor: AppColors.trainingBg,
        appBar: AppBar(
          backgroundColor: AppColors.trainingBg,
          leading: IconButton(
            icon: const Icon(Icons.close),
            onPressed: () => _confirmExit(),
          ),
          title: Column(
            children: [
              Text('${_current + 1} / $total',
                  style: const TextStyle(
                      color: Colors.white,
                      fontSize: 15,
                      fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: progress,
                  minHeight: 3,
                  backgroundColor: AppColors.trainingBorder,
                  valueColor:
                      const AlwaysStoppedAnimation(AppColors.primary),
                ),
              ),
            ],
          ),
          centerTitle: true,
        ),
        body: SafeArea(
          child: Column(
            children: [
              // 大 GIF
              Expanded(
                child: Container(
                  margin: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: AppColors.trainingCard,
                    borderRadius: BorderRadius.circular(AppRadius.lg),
                    border: Border.all(color: AppColors.trainingBorder),
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: ExerciseImage(
                    path: item.gifUrl,
                    fit: BoxFit.contain,
                  ),
                ),
              ),

              // 动作信息 + 输入
              Container(
                padding: const EdgeInsets.all(20),
                decoration: const BoxDecoration(
                  color: AppColors.trainingSurface,
                  borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      item.name,
                      style: const TextStyle(
                          color: Colors.white,
                          fontSize: 20,
                          fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${item.targetZh ?? ''} · ${item.equipmentZh ?? ''}',
                      style: const TextStyle(
                          color: AppColors.textOnDarkSecondary, fontSize: 13),
                    ),
                    if (item.note != null && item.note!.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text(item.note!,
                          style: const TextStyle(
                              color: AppColors.textOnDarkSecondary,
                              fontSize: 12,
                              height: 1.5)),
                    ],
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: _inputField(
                            controller: _weightCtrl,
                            label: '重量',
                            unit: 'kg',
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: _inputField(
                            controller: _repsCtrl,
                            label: '次数',
                            unit: '次',
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            '${item.sets} 组 × ${item.reps}',
                            style: const TextStyle(
                                color: AppColors.primary,
                                fontSize: 15,
                                fontWeight: FontWeight.w700),
                          ),
                        ),
                        if (_current > 0)
                          TextButton(
                            onPressed: _prev,
                            child: const Text('上一个',
                                style: TextStyle(color: Colors.white70)),
                          ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: _saving ? null : _next,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.primary,
                          foregroundColor: Colors.black,
                          minimumSize: const Size(double.infinity, 54),
                        ),
                        child: _saving
                            ? const SizedBox(
                                width: 22,
                                height: 22,
                                child: CircularProgressIndicator(
                                    strokeWidth: 2.5, color: Colors.black))
                            : Text(
                                _current == total - 1 ? '完成训练' : '完成，下一个',
                                style: const TextStyle(
                                    fontSize: 16, fontWeight: FontWeight.w700),
                              ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _inputField({
    required TextEditingController controller,
    required String label,
    required String unit,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
      decoration: BoxDecoration(
        color: AppColors.trainingCard,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.trainingBorder),
      ),
      child: TextField(
        controller: controller,
        keyboardType: TextInputType.number,
        style: const TextStyle(
            color: Colors.white, fontSize: 18, fontWeight: FontWeight.w700),
        decoration: InputDecoration(
          border: InputBorder.none,
          labelText: label,
          labelStyle:
              const TextStyle(color: AppColors.textOnDarkSecondary, fontSize: 12),
          suffixText: unit,
          suffixStyle:
              const TextStyle(color: AppColors.textOnDarkSecondary, fontSize: 12),
        ),
      ),
    );
  }

  void _next() {
    _logs[_current].weight = double.tryParse(_weightCtrl.text);
    _logs[_current].reps = int.tryParse(_repsCtrl.text);

    if (_current < _day.items.length - 1) {
      setState(() {
        _current++;
        _prefill();
      });
    } else {
      setState(() => _saving = true);
      _finish();
    }
  }

  void _prev() {
    if (_current > 0) {
      setState(() {
        _current--;
        _prefill();
      });
    }
  }

  Future<void> _confirmExit() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('退出训练？'),
        content: const Text('当前进度不会保存'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('继续')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('退出')),
        ],
      ),
    );
    if (ok == true && mounted) context.pop();
  }

  Widget _finishView() {
    return Theme(
      data: AppTheme.dark,
      child: Scaffold(
        backgroundColor: AppColors.trainingBg,
        body: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: AppColors.primaryGradient,
                    ),
                    child: const Icon(Icons.check, color: Colors.black, size: 48),
                  ),
                  const SizedBox(height: 24),
                  const Text('训练完成！',
                      style: TextStyle(
                          color: Colors.white,
                          fontSize: 24,
                          fontWeight: FontWeight.w800)),
                  const SizedBox(height: 8),
                  Text(
                    '完成 ${_day.items.length} 个动作 · 记录已保存',
                    style: const TextStyle(
                        color: AppColors.textOnDarkSecondary, fontSize: 14),
                  ),
                  const SizedBox(height: 32),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: () => context.go('/'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.primary,
                        foregroundColor: Colors.black,
                        minimumSize: const Size(double.infinity, 52),
                      ),
                      child: const Text('返回首页',
                          style: TextStyle(fontWeight: FontWeight.w700)),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _SetLog {
  final String exerciseId;
  int? sets;
  int? reps;
  double? weight;
  _SetLog({required this.exerciseId});
}
