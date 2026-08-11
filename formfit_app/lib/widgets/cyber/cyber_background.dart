import 'package:flutter/material.dart';
import 'package:particles_network/particles_network.dart';

import '../../theme/app_theme.dart';

/// 科技感背景：深色底 + 网格 + 粒子网络 + 撞色光晕。
/// 作为屏幕最底层，内容叠在上面。
class CyberBackground extends StatelessWidget {
  final Widget child;
  final bool showParticles;
  const CyberBackground({
    super.key,
    required this.child,
    this.showParticles = true,
  });

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        // 底色
        const Positioned.fill(child: ColoredBox(color: AppColors.bg)),
        // 网格
        const Positioned.fill(child: CustomPaint(painter: _GridPainter())),
        // 撞色光晕
        Positioned(
          top: -100, right: -60,
          child: _glow(AppColors.hot, 260),
        ),
        Positioned(
          bottom: -80, left: -80,
          child: _glow(AppColors.cyan, 240),
        ),
        Positioned(
          top: 200, left: 60,
          child: _glow(AppColors.energy.withValues(alpha: 0.25), 180),
        ),
        // 粒子网络
        if (showParticles)
          Positioned.fill(
            child: ParticleNetwork(
              particleCount: 40,
              maxSpeed: 0.4,
              maxSize: 1.6,
              lineWidth: 0.6,
              lineDistance: 110,
              particleColor: AppColors.energy.withValues(alpha: 0.7),
              lineColor: AppColors.energy.withValues(alpha: 0.25),
              touchColor: AppColors.cyan,
              touchActivation: false,
              hoverEffect: false,
              isComplex: true,
            ),
          ),
        // 内容
        Positioned.fill(child: child),
      ],
    );
  }

  Widget _glow(Color color, double size) {
    return IgnorePointer(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            colors: [color.withValues(alpha: 0.3), color.withValues(alpha: 0.0)],
          ),
        ),
      ),
    );
  }
}

/// 科技网格 CustomPainter：细横线 + 透视竖线
class _GridPainter extends CustomPainter {
  const _GridPainter();
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.energy.withValues(alpha: 0.05)
      ..strokeWidth = 0.6;

    const gap = 32.0;
    // 横线
    for (double y = 0; y < size.height; y += gap) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
    // 竖线
    for (double x = 0; x < size.width; x += gap) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }

    // 顶部一条能量线（扫描基线）
    final topPaint = Paint()
      ..shader = LinearGradient(
        colors: [
          Colors.transparent,
          AppColors.energy.withValues(alpha: 0.4),
          Colors.transparent,
        ],
      ).createShader(Rect.fromLTWH(0, 0, size.width, 1));
    canvas.drawRect(Rect.fromLTWH(0, 0, size.width, 1), topPaint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
