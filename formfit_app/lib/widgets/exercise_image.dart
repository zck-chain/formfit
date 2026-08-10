import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';

import '../core/config.dart';
import '../theme/app_theme.dart';

/// 远程动图/图片（带占位与失败态）
class ExerciseImage extends StatelessWidget {
  final String path;
  final double? size;
  final BoxFit fit;
  final BorderRadius? borderRadius;

  const ExerciseImage({
    super.key,
    required this.path,
    this.size,
    this.fit = BoxFit.cover,
    this.borderRadius,
  });

  @override
  Widget build(BuildContext context) {
    final url = AppConfig.resolveUrl(path);
    final isDark = Theme.of(context).brightness == Brightness.dark;
    Widget img = CachedNetworkImage(
      imageUrl: url,
      fit: fit,
      placeholder: (_, __) => Container(
        color: isDark ? AppColors.trainingCard : const Color(0xFFF0F2F5),
        child: const Center(
          child: SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      ),
      errorWidget: (_, __, ___) => Container(
        color: isDark ? AppColors.trainingCard : const Color(0xFFF0F2F5),
        child: const Icon(Icons.image_not_supported_outlined,
            color: AppColors.textMuted),
      ),
    );
    if (borderRadius != null) {
      img = ClipRRect(borderRadius: borderRadius!, child: img);
    }
    if (size != null) {
      img = SizedBox(width: size, height: size, child: img);
    }
    return img;
  }
}
