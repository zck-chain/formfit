import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 提示严重级别，对应不同配色与图标。
enum SafetyNoticeLevel { info, warning, danger }

/// 统一的安全提示 / 免责声明组件。
///
/// 评估结果、计划生成、档案伤病史等所有入口共用本组件，确保文案与样式一致：
/// - [SafetyNoticeLevel.info]：常规免责声明（AI 结果非医疗诊断）。
/// - [SafetyNoticeLevel.warning]：需要注意的安全提示。
/// - [SafetyNoticeLevel.danger]：高风险，强化样式 + 就医/转介引导（[referralText]）。
///
/// 设计遵循 Night Energy 暗色系统，使用 HUD 角标 + 语义色，高风险时左侧加
/// 4px 强调色条与发光，确保不被折叠忽略。该组件始终可见、不可被外部折叠。
class SafetyNotice extends StatelessWidget {
  final String message;
  final SafetyNoticeLevel level;

  /// 高风险时的就医/转介引导文案，置于独立强调行；仅 danger 级别显示。
  final String? referralText;

  /// 标题，默认按级别取中文标题。
  final String? title;

  /// 可选操作（如「了解了」「查看就医建议」）。
  final Widget? action;

  /// 是否显示左侧强调色条（danger 默认开启）。
  final bool? emphasize;

  const SafetyNotice({
    super.key,
    required this.message,
    this.level = SafetyNoticeLevel.info,
    this.referralText,
    this.title,
    this.action,
    this.emphasize,
  });

  Color get _color => switch (level) {
        SafetyNoticeLevel.info => AppColors.cyan,
        SafetyNoticeLevel.warning => AppColors.warning,
        SafetyNoticeLevel.danger => AppColors.danger,
      };

  IconData get _icon => switch (level) {
        SafetyNoticeLevel.info => Icons.shield_outlined,
        SafetyNoticeLevel.warning => Icons.warning_amber_rounded,
        SafetyNoticeLevel.danger => Icons.error_outline_rounded,
      };

  String get _defaultTitle => switch (level) {
        SafetyNoticeLevel.info => '安全提示',
        SafetyNoticeLevel.warning => '请注意',
        SafetyNoticeLevel.danger => '高风险提示',
      };

  @override
  Widget build(BuildContext context) {
    final color = _color;
    final strong = emphasize ?? (level == SafetyNoticeLevel.danger);
    final hasReferral =
        level == SafetyNoticeLevel.danger && referralText != null && referralText!.trim().isNotEmpty;

    return Container(
      decoration: BoxDecoration(
        color: color.withValues(alpha: strong ? .12 : .08),
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(color: color.withValues(alpha: strong ? .55 : .3)),
        boxShadow: strong
            ? [BoxShadow(color: color.withValues(alpha: .18), blurRadius: 16)]
            : null,
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // 左侧强调色条
            Container(
              width: strong ? 4 : 3,
              color: color,
            ),
            Expanded(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(_icon, color: color, size: 18),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          title ?? _defaultTitle,
                          style: TextStyle(
                            color: color,
                            fontSize: 14,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 0.2,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    message,
                    style: TextStyle(
                      color: AppColors.textPrimary.withValues(alpha: .92),
                      fontSize: 13,
                      height: 1.55,
                    ),
                  ),
                  if (hasReferral) ...[
                    const SizedBox(height: 12),
                    _ReferralBar(color: color, text: referralText!),
                  ],
                  if (action != null) ...[
                    const SizedBox(height: 12),
                    action!,
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
      ),
    );
  }
}

/// 高风险转介引导条：突出展示就医建议。
class _ReferralBar extends StatelessWidget {
  final Color color;
  final String text;
  const _ReferralBar({required this.color, required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .14),
        borderRadius: BorderRadius.circular(8),
        border: Border(left: BorderSide(color: color, width: 3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.local_hospital_outlined, color: color, size: 16),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                color: AppColors.textPrimary,
                fontSize: 12.5,
                height: 1.5,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
