import 'package:flutter/material.dart';

/// FormFit 设计系统 —— 参考 Keep 的活力健身风格
/// 主色：活力青绿；训练场景深色底；内容白色大圆角卡片；粗标题；渐变主按钮。
class AppColors {
  AppColors._();

  // 品牌主色（Keep 青绿系）
  static const Color primary = Color(0xFF00D68F);
  static const Color primaryDark = Color(0xFF00B87A);
  static const Color primaryDeep = Color(0xFF009966);
  static const Color primarySoft = Color(0xFFE6FBF4);

  // 渐变（主按钮/强调区域）
  static const LinearGradient primaryGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF2BE6A6), Color(0xFF00B87A)],
  );

  // 深色训练背景（跟练/运动中沉浸场景）
  static const Color trainingBg = Color(0xFF0E1114);
  static const Color trainingSurface = Color(0xFF1A1F25);
  static const Color trainingCard = Color(0xFF232931);
  static const Color trainingBorder = Color(0xFF2E353D);

  // 浅色内容背景
  static const Color bg = Color(0xFFF6F8FA);
  static const Color surface = Colors.white;
  static const Color card = Colors.white;

  // 文字
  static const Color textPrimary = Color(0xFF101418);
  static const Color textSecondary = Color(0xFF6B7280);
  static const Color textMuted = Color(0xFF9CA3AF);
  static const Color textOnDark = Colors.white;
  static const Color textOnDarkSecondary = Color(0xFFAEB5BD);

  // 语义色
  static const Color success = Color(0xFF00B87A);
  static const Color warning = Color(0xFFFFA726);
  static const Color danger = Color(0xFFFF4D4F);
  static const Color info = Color(0xFF3B82F6);

  // 方向标签
  static const Color gain = Color(0xFFFF7A45);   // 增肌 橙
  static const Color fatLoss = Color(0xFFFF4D4F); // 减脂 红
  static const Color rehab = Color(0xFFFFA726);   // 康复 黄
  static const Color maintain = Color(0xFF3B82F6); // 维持 蓝
}

class AppRadius {
  AppRadius._();
  static const double xs = 8;
  static const double sm = 12;
  static const double md = 16;
  static const double lg = 20;
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

  static ThemeData get light {
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        primary: AppColors.primary,
        surface: AppColors.surface,
        brightness: Brightness.light,
      ),
      scaffoldBackgroundColor: AppColors.bg,
      fontFamily: 'PingFang SC',
    );
    return base.copyWith(
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.bg,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: AppColors.textPrimary,
          fontSize: 20,
          fontWeight: FontWeight.w700,
        ),
      ),
      textTheme: base.textTheme.apply(
        bodyColor: AppColors.textPrimary,
        displayColor: AppColors.textPrimary,
      ),
      cardTheme: CardThemeData(
        color: AppColors.card,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          elevation: 0,
          minimumSize: const Size(double.infinity, 52),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.pill),
          ),
          textStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surface,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: Color(0xFFE5E7EB)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: Color(0xFFE5E7EB)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: AppColors.primary, width: 1.5),
        ),
      ),
    );
  }

  static ThemeData get dark {
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primary,
        primary: AppColors.primary,
        surface: AppColors.trainingSurface,
        brightness: Brightness.dark,
      ),
      scaffoldBackgroundColor: AppColors.trainingBg,
      fontFamily: 'PingFang SC',
    );
    return base.copyWith(
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.trainingBg,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: Colors.white,
          fontSize: 20,
          fontWeight: FontWeight.w700,
        ),
      ),
      textTheme: base.textTheme.apply(
        bodyColor: AppColors.textOnDark,
        displayColor: AppColors.textOnDark,
      ),
      cardTheme: CardThemeData(
        color: AppColors.trainingCard,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          side: const BorderSide(color: AppColors.trainingBorder),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.black,
          elevation: 0,
          minimumSize: const Size(double.infinity, 52),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.pill),
          ),
          textStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.trainingCard,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: AppColors.trainingBorder),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: AppColors.trainingBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          borderSide: const BorderSide(color: AppColors.primary, width: 1.5),
        ),
      ),
    );
  }
}
