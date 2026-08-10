import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// FormFit 设计系统 —— 「Night Energy / 能量霓虹」
/// 灵感：夜跑灯光、运动饮料撞色、球衣号码。
/// 暗底 + 酸橙黄绿能量主色 + 热粉/电光青撞色，斜切角 signature。
class AppColors {
  AppColors._();

  // ---- 品牌色 ----
  static const Color energy = Color(0xFFD7FF3A); // 酸橙黄绿，主色
  static const Color energyDim = Color(0xFFB8E02A);
  static const Color hot = Color(0xFFFF4D8D); // 热粉撞色
  static const Color cyan = Color(0xFF3DE0FF); // 电光青撞色
  static const Color purple = Color(0xFF7C5CFF); // 辅助紫

  // 能量渐变（按钮/英雄卡）
  static const LinearGradient energyGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFE8FF6A), Color(0xFFC8F020)],
  );
  static const LinearGradient hotGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFFF7AA8), Color(0xFFFF3D7D)],
  );
  static const LinearGradient cyanGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF6BE9FF), Color(0xFF22C8F0)],
  );

  // ---- 暗色（App 主基调，训练沉浸感）----
  static const Color bg = Color(0xFF0E0E12);
  static const Color surface = Color(0xFF16161D);
  static const Color card = Color(0xFF1E1E27);
  static const Color cardHover = Color(0xFF262630);
  static const Color border = Color(0xFF2C2C38);
  static const Color borderBright = Color(0xFF3A3A48);

  static const Color textPrimary = Color(0xFFF5F5F7);
  static const Color textSecondary = Color(0xFF9B9BA8);
  static const Color textMuted = Color(0xFF6A6A78);

  // ---- 亮色（内容卡片、输入框）----
  static const Color lightBg = Color(0xFFFAFAF8);
  static const Color lightSurface = Colors.white;

  // ---- 语义 ----
  static const Color success = Color(0xFF3DD68C);
  static const Color warning = Color(0xFFFFB02E);
  static const Color danger = Color(0xFFFF5A5F);
  static const Color info = Color(0xFF5B9DFF);

  // 评估方向
  static const Color gain = Color(0xFFFF7A45); // 增肌 橙
  static const Color fatLoss = Color(0xFFFF4D8D); // 减脂 粉
  static const Color rehab = Color(0xFFFFB02E); // 康复 黄
  static const Color maintain = Color(0xFF3DE0FF); // 维持 青

  // ---- 向后兼容别名（旧色名 → 新色，全局暗色）----
  static const Color primary = energy;
  static const LinearGradient primaryGradient = energyGradient;
  static const Color trainingBg = bg;
  static const Color trainingSurface = surface;
  static const Color trainingCard = card;
  static const Color trainingBorder = border;
  static const Color textOnDark = textPrimary;
  static const Color textOnDarkSecondary = textSecondary;
}

/// 斜切角形状 —— signature 元素
class AppClipper extends CustomClipper<Path> {
  final double cut;
  const AppClipper({this.cut = 14});
  @override
  Path getClip(Size size) {
    final c = cut;
    final path = Path()
      ..moveTo(c, 0)
      ..lineTo(size.width, 0)
      ..lineTo(size.width, size.height - c)
      ..lineTo(size.width - c, size.height)
      ..lineTo(0, size.height)
      ..lineTo(0, c)
      ..close();
    return path;
  }

  @override
  bool shouldReclip(CustomClipper oldClipper) => false;
}

/// 斜切卡片容器（signature 风格）
class CutCard extends StatelessWidget {
  final Widget child;
  final Color? color;
  final EdgeInsetsGeometry padding;
  final Gradient? gradient;
  final Border? border;
  final double cut;
  const CutCard({
    super.key,
    required this.child,
    this.color,
    this.padding = const EdgeInsets.all(16),
    this.gradient,
    this.border,
    this.cut = 14,
  });

  @override
  Widget build(BuildContext context) {
    return ClipPath(
      clipper: AppClipper(cut: cut),
      child: Container(
        padding: padding,
        decoration: BoxDecoration(
          color: gradient == null ? (color ?? AppColors.card) : null,
          gradient: gradient,
          border: border,
        ),
        child: child,
      ),
    );
  }
}

class AppRadius {
  AppRadius._();
  static const double xs = 8;
  static const double sm = 12;
  static const double md = 16;
  static const double lg = 22;
  static const double xl = 28;
  static const double pill = 100;
}

class AppSpacing {
  AppSpacing._();
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 16;
  static const double lg = 24;
  static const double xl = 32;
}

class AppTheme {
  AppTheme._();

  // App 以暗色为主基调
  static ThemeData get dark {
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: const ColorScheme.dark(
        primary: AppColors.energy,
        onPrimary: Colors.black,
        secondary: AppColors.hot,
        surface: AppColors.surface,
        onSurface: AppColors.textPrimary,
        error: AppColors.danger,
      ),
      scaffoldBackgroundColor: AppColors.bg,
    );
    return base.copyWith(
      textTheme: base.textTheme.apply(
        bodyColor: AppColors.textPrimary,
        displayColor: AppColors.textPrimary,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.bg,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: AppColors.textPrimary,
          fontSize: 22,
          fontWeight: FontWeight.w800,
          letterSpacing: -0.3,
        ),
      ),
      cardTheme: CardThemeData(
        color: AppColors.card,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          side: const BorderSide(color: AppColors.border),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.energy,
          foregroundColor: Colors.black,
          elevation: 0,
          minimumSize: const Size(double.infinity, 54),
          textStyle: GoogleFonts.spaceGrotesk(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.2,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.sm),
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.card,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: AppColors.energy, width: 1.5),
        ),
        labelStyle: const TextStyle(color: AppColors.textSecondary),
        hintStyle: const TextStyle(color: AppColors.textMuted),
      ),
      bottomNavigationBarTheme: const BottomNavigationBarThemeData(
        backgroundColor: AppColors.surface,
        selectedItemColor: AppColors.energy,
        unselectedItemColor: AppColors.textMuted,
        type: BottomNavigationBarType.fixed,
        elevation: 0,
      ),
    );
  }

  /// 展示标题字体（Space Grotesk 几何运动感）
  static TextStyle display(double size, {Color? color, FontWeight? weight}) {
    return GoogleFonts.spaceGrotesk(
      fontSize: size,
      fontWeight: weight ?? FontWeight.w700,
      color: color ?? AppColors.textPrimary,
      letterSpacing: -0.5,
      height: 1.1,
    );
  }
}
