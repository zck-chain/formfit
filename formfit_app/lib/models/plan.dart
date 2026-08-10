import 'exercise.dart';

/// 训练计划中的单个动作项
class PlanItem {
  final String exerciseId;
  final String name;
  final String? targetZh;
  final String? categoryZh;
  final String? equipmentZh;
  final String gifUrl;
  final String image;
  final List<String> stepsZh;
  final int sets;
  final String reps;
  final String? tempo;
  final int? restSec;
  final String? note;

  PlanItem({
    required this.exerciseId,
    required this.name,
    this.targetZh,
    this.categoryZh,
    this.equipmentZh,
    required this.gifUrl,
    required this.image,
    this.stepsZh = const [],
    required this.sets,
    required this.reps,
    this.tempo,
    this.restSec,
    this.note,
  });

  factory PlanItem.fromJson(Map<String, dynamic> json) => PlanItem(
        exerciseId: json['exercise_id']?.toString() ?? '',
        name: json['name'] ?? '',
        targetZh: json['target_zh'],
        categoryZh: json['category_zh'],
        equipmentZh: json['equipment_zh'],
        gifUrl: json['gif_url'] ?? '',
        image: json['image'] ?? '',
        stepsZh:
            (json['steps_zh'] as List?)?.map((e) => e.toString()).toList() ??
                const [],
        sets: json['sets'] ?? 3,
        reps: json['reps']?.toString() ?? '8-12',
        tempo: json['tempo'],
        restSec: json['rest_sec'],
        note: json['note'],
      );

  Exercise toExercise() => Exercise(
        id: exerciseId,
        name: name,
        category: '',
        categoryZh: categoryZh ?? '',
        equipment: '',
        equipmentZh: equipmentZh ?? '',
        target: '',
        targetZh: targetZh ?? '',
        secondaryMuscles: const [],
        gifUrl: gifUrl,
        image: image,
        stepsZh: stepsZh,
      );
}

class PlanDay {
  final String dayLabel;
  final String? focus;
  final List<PlanItem> items;

  PlanDay({required this.dayLabel, this.focus, required this.items});

  factory PlanDay.fromJson(Map<String, dynamic> json) => PlanDay(
        dayLabel: json['day_label'] ?? '',
        focus: json['focus'],
        items: (json['items'] as List?)
                ?.map((e) => PlanItem.fromJson(e as Map<String, dynamic>))
                .toList() ??
            const [],
      );
}

class PlanContent {
  final String title;
  final String? goal;
  final int weeks;
  final int daysPerWeek;
  final String? notes;
  final List<PlanDay> days;

  PlanContent({
    required this.title,
    this.goal,
    this.weeks = 4,
    this.daysPerWeek = 3,
    this.notes,
    required this.days,
  });

  factory PlanContent.fromJson(Map<String, dynamic> json) => PlanContent(
        title: json['title'] ?? '我的训练计划',
        goal: json['goal'],
        weeks: json['weeks'] ?? 4,
        daysPerWeek: json['days_per_week'] ?? 3,
        notes: json['notes'],
        days: (json['days'] as List?)
                ?.map((e) => PlanDay.fromJson(e as Map<String, dynamic>))
                .toList() ??
            const [],
      );
}

class Plan {
  final int id;
  final String title;
  final PlanContent content;
  final bool isActive;
  final DateTime? createdAt;

  Plan({
    required this.id,
    required this.title,
    required this.content,
    this.isActive = true,
    this.createdAt,
  });

  factory Plan.fromJson(Map<String, dynamic> json) => Plan(
        id: json['id'],
        title: json['title'] ?? '',
        content: PlanContent.fromJson(json['content'] ?? {}),
        isActive: json['is_active'] ?? true,
        createdAt: json['created_at'] != null
            ? DateTime.tryParse(json['created_at'].toString())
            : null,
      );
}
