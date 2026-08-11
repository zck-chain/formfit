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

  /// BE-8：风险等级，如 "low" / "medium" / "high"。后端未就绪时为 null。
  final String? riskLevel;

  /// BE-8：高风险情形下的就医/转介引导文案。
  final String? referralAdvice;

  Assessment({
    required this.id,
    required this.direction,
    this.bodyType,
    this.summary,
    this.observed = const [],
    this.safetyNotes,
    this.mediaUrl,
    this.createdAt,
    this.riskLevel,
    this.referralAdvice,
  });

  /// 是否为高风险：优先取后端显式标记；字段缺失时基于文案做启发式判断，
  /// 确保在 BE-8 高风险标记上线前也能以强化样式提示。
  bool get isHighRisk {
    final level = riskLevel?.toLowerCase();
    if (level == 'high' || level == 'critical' || level == 'severe') return true;
    final text = (safetyNotes ?? '').toLowerCase();
    if (text.isEmpty) return false;
    const keywords = [
      '就医', '立即就医', '疼痛', '剧痛', '麻木', '外伤', '骨折',
      '脱位', '急性', '放射痛', '头晕', '胸闷', '呼吸困难',
      'seek medical', 'doctor', 'emergency', 'severe pain', 'numbness',
    ];
    return keywords.any((k) => text.contains(k.toLowerCase()));
  }

  String get directionZh => switch (direction) {
        'gain' => '增肌',
        'fat_loss' => '减脂',
        'rehab' => '康复调整',
        _ => '维持',
      };

  String? get riskLevelZh {
    final level = riskLevel?.toLowerCase();
    return switch (level) {
      'low' => '低风险',
      'medium' || 'moderate' => '中等风险',
      'high' => '高风险',
      'critical' || 'severe' => '需立即关注',
      _ => null,
    };
  }

  factory Assessment.fromJson(Map<String, dynamic> json) => Assessment(
        id: json['id'],
        direction: json['direction'] ?? 'maintain',
        bodyType: json['body_type'],
        summary: json['summary'],
        observed: (json['observed'] as List?)?.map((e) => e.toString()).toList() ??
            const [],
        safetyNotes: json['safety_notes'],
        mediaUrl: json['media_url'],
        riskLevel: json['risk_level']?.toString(),
        referralAdvice: json['referral_advice'] ?? json['referral'],
        createdAt: json['created_at'] != null
            ? DateTime.tryParse(json['created_at'].toString())
            : null,
      );
}
