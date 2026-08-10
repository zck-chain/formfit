/// 用户与档案
class AppUser {
  final int id;
  final String email;
  final String? nickname;
  final String role;
  final bool isActive;

  AppUser({
    required this.id,
    required this.email,
    this.nickname,
    required this.role,
    required this.isActive,
  });

  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
        id: json['id'],
        email: json['email'] ?? '',
        nickname: json['nickname'],
        role: json['role'] ?? 'user',
        isActive: json['is_active'] ?? true,
      );
}

class UserProfile {
  final String? gender; // male / female / other
  final int? age;
  final double? heightCm;
  final double? weightKg;
  final String? goal; // 增肌/减脂/塑形/维持/康复
  final String? level; // beginner/intermediate/advanced
  final int? daysPerWeek;
  final List<String> availableEquipment;
  final String? injuryNotes;
  final List<String> contraindicatedParts;

  UserProfile({
    this.gender,
    this.age,
    this.heightCm,
    this.weightKg,
    this.goal,
    this.level,
    this.daysPerWeek,
    this.availableEquipment = const [],
    this.injuryNotes,
    this.contraindicatedParts = const [],
  });

  double? get bmi {
    if (heightCm == null || weightKg == null || heightCm == 0) return null;
    final m = heightCm! / 100;
    return weightKg! / (m * m);
  }

  UserProfile copyWith({
    String? gender,
    int? age,
    double? heightCm,
    double? weightKg,
    String? goal,
    String? level,
    int? daysPerWeek,
    List<String>? availableEquipment,
    String? injuryNotes,
    List<String>? contraindicatedParts,
  }) {
    return UserProfile(
      gender: gender ?? this.gender,
      age: age ?? this.age,
      heightCm: heightCm ?? this.heightCm,
      weightKg: weightKg ?? this.weightKg,
      goal: goal ?? this.goal,
      level: level ?? this.level,
      daysPerWeek: daysPerWeek ?? this.daysPerWeek,
      availableEquipment: availableEquipment ?? this.availableEquipment,
      injuryNotes: injuryNotes ?? this.injuryNotes,
      contraindicatedParts: contraindicatedParts ?? this.contraindicatedParts,
    );
  }

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
        gender: json['gender'],
        age: json['age'],
        heightCm: (json['height_cm'] as num?)?.toDouble(),
        weightKg: (json['weight_kg'] as num?)?.toDouble(),
        goal: json['goal'],
        level: json['level'],
        daysPerWeek: json['days_per_week'],
        availableEquipment: (json['available_equipment'] as List?)
                ?.map((e) => e.toString())
                .toList() ??
            const [],
        injuryNotes: json['injury_notes'],
        contraindicatedParts: (json['contraindicated_parts'] as List?)
                ?.map((e) => e.toString())
                .toList() ??
            const [],
      );

  Map<String, dynamic> toJson() => {
        'gender': gender,
        'age': age,
        'height_cm': heightCm,
        'weight_kg': weightKg,
        'goal': goal,
        'level': level,
        'days_per_week': daysPerWeek,
        'available_equipment': availableEquipment,
        'injury_notes': injuryNotes,
        'contraindicated_parts': contraindicatedParts,
      };
}
