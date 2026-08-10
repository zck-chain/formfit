import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';

/// 科技感 HUD 卡片：四角 L 形角标 + 细边框 + 可选发光。
/// 可选 [glass] 模式做玻璃拟态背景。
class HudCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color? color;
  final Color? borderColor;
  final Color? cornerColor;
  final bool glass;
  final double blur;
  final double cornerLength;
  final double radius;
  final bool glow;

  const HudCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.color,
    this.borderColor,
    this.cornerColor,
    this.glass = false,
    this.blur = 18,
    this.cornerLength = 14,
    this.radius = 4,
    this.glow = false,
  });

  @override
  Widget build(BuildContext context) {
    final bc = borderColor ?? AppColors.border;
    final cc = cornerColor ?? AppColors.energy;

    return CustomPaint(
      painter: _HudFramePainter(
        borderColor: bc,
        cornerColor: cc,
        cornerLength: cornerLength,
        radius: radius,
        glow: glow,
      ),
      child: ClipPath(
        clipper: _HudClipper(cornerLength: cornerLength, radius: radius),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            color: glass
                ? (color ?? AppColors.card).withValues(alpha: 0.55)
                : (color ?? AppColors.card),
            border: glass
                ? Border.all(color: Colors.white.withValues(alpha: 0.08))
                : null,
            gradient: glass
                ? LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [
                      Colors.white.withValues(alpha: 0.08),
                      Colors.white.withValues(alpha: 0.02),
                    ],
                  )
                : null,
          ),
          child: glass
              ? BackdropFilter(
                  filter: ui.ImageFilter.blur(sigmaX: blur, sigmaY: blur),
                  child: child,
                )
              : child,
        ),
      ),
    );
  }
}

class _HudFramePainter extends CustomPainter {
  final Color borderColor;
  final Color cornerColor;
  final double cornerLength;
  final double radius;
  final bool glow;
  _HudFramePainter({
    required this.borderColor,
    required this.cornerColor,
    required this.cornerLength,
    required this.radius,
    required this.glow,
  });

  @override
  void paint(Canvas canvas, Size size) {
    // 细边框
    final borderPaint = Paint()
      ..color = borderColor
      ..strokeWidth = 1
      ..style = PaintingStyle.stroke;
    final rect = RRect.fromRectAndRadius(
      Rect.fromLTWH(0, 0, size.width, size.height),
      Radius.circular(radius),
    );
    canvas.drawRRect(rect, borderPaint);

    // 四角 L 形角标
    final cornerPaint = Paint()
      ..color = cornerColor
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.square;
    if (glow) {
      cornerPaint.maskFilter = const MaskFilter.blur(BlurStyle.outer, 4);
    }
    final l = cornerLength;
    final w = size.width;
    final h = size.height;
    // 左上
    canvas.drawLine(Offset.zero, Offset(l, 0), cornerPaint);
    canvas.drawLine(Offset.zero, Offset(0, l), cornerPaint);
    // 右上
    canvas.drawLine(Offset(w, 0), Offset(w - l, 0), cornerPaint);
    canvas.drawLine(Offset(w, 0), Offset(w, l), cornerPaint);
    // 左下
    canvas.drawLine(Offset(0, h), Offset(l, h), cornerPaint);
    canvas.drawLine(Offset(0, h), Offset(0, h - l), cornerPaint);
    // 右下
    canvas.drawLine(Offset(w, h), Offset(w - l, h), cornerPaint);
    canvas.drawLine(Offset(w, h), Offset(w, h - l), cornerPaint);
  }

  @override
  bool shouldRepaint(covariant _HudFramePainter oldDelegate) =>
      oldDelegate.borderColor != borderColor ||
      oldDelegate.cornerColor != cornerColor;
}

class _HudClipper extends CustomClipper<Path> {
  final double cornerLength;
  final double radius;
  _HudClipper({required this.cornerLength, required this.radius});

  @override
  Path getClip(Size size) {
    // 只剪圆角，角标线条在外
    return Path()
      ..addRRect(RRect.fromRectAndRadius(
        Rect.fromLTWH(0, 0, size.width, size.height),
        Radius.circular(radius),
      ));
  }

  @override
  bool shouldReclip(covariant _HudClipper oldClipper) => false;
}
