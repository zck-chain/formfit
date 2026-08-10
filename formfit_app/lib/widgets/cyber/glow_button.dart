import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../../theme/app_theme.dart';

/// 能量按钮：斜切 + 能量渐变 + 外发光 + 扫描光效（按下/加载态）。
class GlowButton extends StatefulWidget {
  final String label;
  final VoidCallback? onTap;
  final bool loading;
  final IconData? icon;
  final Color? color;
  final double height;
  final bool expanded;

  const GlowButton({
    super.key,
    required this.label,
    this.onTap,
    this.loading = false,
    this.icon,
    this.color,
    this.height = 54,
    this.expanded = true,
  });

  @override
  State<GlowButton> createState() => _GlowButtonState();
}

class _GlowButtonState extends State<GlowButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onTap != null && !widget.loading;
    final gradient = LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: widget.color != null
          ? [widget.color!, widget.color!]
          : const [Color(0xFFE8FF6A), Color(0xFFC8F020)],
    );

    final btn = GestureDetector(
      onTapDown: enabled ? (_) => setState(() => _pressed = true) : null,
      onTapUp: enabled ? (_) => setState(() => _pressed = false) : null,
      onTapCancel: () => setState(() => _pressed = false),
      onTap: enabled ? widget.onTap : null,
      child: AnimatedScale(
        scale: _pressed ? 0.98 : 1.0,
        duration: 80.ms,
        child: ClipPath(
          clipper: const AppClipper(cut: 12),
          child: Container(
            height: widget.height,
            width: widget.expanded ? double.infinity : null,
            padding: const EdgeInsets.symmetric(horizontal: 22),
            decoration: BoxDecoration(
              gradient: enabled ? gradient : null,
              color: enabled ? null : AppColors.card,
              border: enabled ? null : Border.all(color: AppColors.border),
              boxShadow: enabled
                  ? [
                      BoxShadow(
                        color: (widget.color ?? AppColors.energy)
                            .withValues(alpha: 0.5),
                        blurRadius: 24,
                        offset: const Offset(0, 6),
                      ),
                    ]
                  : null,
            ),
            child: Row(
              mainAxisSize:
                  widget.expanded ? MainAxisSize.max : MainAxisSize.min,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                if (widget.loading)
                  const SizedBox(
                    width: 20, height: 20,
                    child: CircularProgressIndicator(
                        strokeWidth: 2.5, color: Colors.black),
                  )
                else ...[
                  if (widget.icon != null) ...[
                    Icon(widget.icon, color: Colors.black, size: 20),
                    const SizedBox(width: 8),
                  ],
                  Text(
                    widget.label,
                    style: AppTheme.display(16,
                        color: enabled ? Colors.black : AppColors.textMuted,
                        weight: FontWeight.w800),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );

    // 空闲时的呼吸光（仅主按钮）
    if (enabled && widget.color == null) {
      return btn
          .animate(onPlay: (c) => c.repeat(reverse: true))
          .shimmer(duration: 2200.ms, color: Colors.white.withValues(alpha: 0.25))
          .then()
          .blurXY(end: 10, duration: 2200.ms, curve: Curves.easeInOut);
    }
    return btn;
  }
}

/// 数据标签：等宽字体 + 方括号外壳，HUD/终端感
class DataTag extends StatelessWidget {
  final String label;
  final String value;
  final Color? color;
  const DataTag({super.key, required this.label, required this.value, this.color});

  @override
  Widget build(BuildContext context) {
    final c = color ?? AppColors.energy;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.1),
        border: Border.all(color: c.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('// $label ',
              style: TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 11,
                  color: AppColors.textSecondary)),
          Text(value,
              style: TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: c)),
        ],
      ),
    );
  }
}
