/// 健身动作（对应后端 ExerciseOut 精简结构）
class Exercise {
  final String id;
  final String name;
  final String category;
  final String categoryZh;
  final String equipment;
  final String equipmentZh;
  final String target;
  final String targetZh;
  final List<String> secondaryMuscles;
  final String gifUrl;
  final String image;
  final List<String> stepsZh;

  Exercise({
    required this.id,
    required this.name,
    required this.category,
    required this.categoryZh,
    required this.equipment,
    required this.equipmentZh,
    required this.target,
    required this.targetZh,
    required this.secondaryMuscles,
    required this.gifUrl,
    required this.image,
    required this.stepsZh,
  });

  factory Exercise.fromJson(Map<String, dynamic> json) {
    return Exercise(
      id: json['id']?.toString() ?? '',
      name: json['name'] ?? '',
      category: json['category'] ?? '',
      categoryZh: json['category_zh'] ?? json['category'] ?? '',
      equipment: json['equipment'] ?? '',
      equipmentZh: json['equipment_zh'] ?? json['equipment'] ?? '',
      target: json['target'] ?? '',
      targetZh: json['target_zh'] ?? json['target'] ?? '',
      secondaryMuscles:
          (json['secondary_muscles'] as List?)?.map((e) => e.toString()).toList() ??
              [],
      gifUrl: json['gif_url'] ?? '',
      image: json['image'] ?? '',
      stepsZh: (json['steps_zh'] as List?)?.map((e) => e.toString()).toList() ?? [],
    );
  }
}
