/// 体态评估结果
class Assessment {
  final int id;
  final String direction; // gain/fat_loss/rehab/maintain
  final String? bodyType;
  final String? summary;
  final List<String> observed;
  final String? safetyNotes;
  final String? mediaUrl;
  final DateTime? createdAt;

  Assessment({
    required this.id,
    required this.direction,
    this.bodyType,
    this.summary,
    this.observed = const [],
    this.safetyNotes,
    this.mediaUrl,
    this.createdAt,
  });

  String get directionZh => switch (direction) {
        'gain' => '增肌',
        'fat_loss' => '减脂',
        'rehab' => '康复调整',
        _ => '维持',
      };

  factory Assessment.fromJson(Map<String, dynamic> json) => Assessment(
        id: json['id'],
        direction: json['direction'] ?? 'maintain',
        bodyType: json['body_type'],
        summary: json['summary'],
        observed: (json['observed'] as List?)?.map((e) => e.toString()).toList() ??
            const [],
        safetyNotes: json['safety_notes'],
        mediaUrl: json['media_url'],
        createdAt: json['created_at'] != null
            ? DateTime.tryParse(json['created_at'].toString())
            : null,
      );
}
