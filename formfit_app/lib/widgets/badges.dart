import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 方向标签（增肌/减脂/康复/维持）
class DirectionBadge extends StatelessWidget {
  final String direction;
  const DirectionBadge({super.key, required this.direction});

  @override
  Widget build(BuildContext context) {
    final (text, color) = switch (direction) {
      'gain' => ('增肌', AppColors.gain),
      'fat_loss' => ('减脂', AppColors.fatLoss),
      'rehab' => ('康复调整', AppColors.rehab),
      _ => ('维持', AppColors.maintain),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(AppRadius.pill),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: color,
          fontSize: 14,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

/// 通用状态标签
class StatusTag extends StatelessWidget {
  final String text;
  final Color color;
  const StatusTag({super.key, required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        text,
        style: TextStyle(
            color: color, fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}
