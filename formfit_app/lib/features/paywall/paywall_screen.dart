import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/payment.dart';
import '../../theme/app_theme.dart';
import '../../widgets/cyber/cyber_background.dart';
import '../../widgets/cyber/glow_button.dart';
import '../../widgets/cyber/hud_card.dart';
import '../../widgets/safety_notice.dart';
import 'payment_controller.dart';
import 'pro_gate.dart';

/// 付费墙（PRO 升级页）。
///
/// 可作为全屏弹窗 [push]，返回 `true` 表示用户在本次会话内成功开通。
/// 金额全部来自后端 `/api/payment/plans`，前端不硬编码。
class PaywallScreen extends ConsumerWidget {
  /// 触发来源（如「体态评估」「生成计划」），用于文案。
  final String? source;

  /// 唤起原因（需要 PRO / 免费额度已用尽），决定标题文案。
  final PaywallReason? reason;

  const PaywallScreen({super.key, this.source, this.reason});

  /// 以全屏对话框形式打开付费墙，返回是否成功开通。
  static Future<T?> push<T>(
    BuildContext context, {
    String? source,
    PaywallReason? reason,
  }) {
    return Navigator.of(context).push<T>(
      MaterialPageRoute(
        builder: (_) => PaywallScreen(source: source, reason: reason),
        fullscreenDialog: true,
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(paymentControllerProvider);
    final controller = ref.read(paymentControllerProvider.notifier);
    final selfCheckout = ref.watch(selfServiceCheckoutEnabledProvider);

    // 支付/恢复成功后关闭并回传 true。
    ref.listen(paymentControllerProvider, (_, next) {
      if (next.stage == PurchaseStage.success) {
        Navigator.of(context).maybePop(true);
      }
    });

    return Scaffold(
      body: CyberBackground(
        showParticles: false,
        child: SafeArea(
          child: Column(
            children: [
              _topBar(context),
              Expanded(
                child: !selfCheckout
                    ? _webClosedContent(
                        context, reason ?? const PaywallReason())
                    : state.isLoading
                        ? const Center(child: CircularProgressIndicator())
                        : state.stage == PurchaseStage.error &&
                                state.plans.isEmpty
                            ? _loadError(controller, state.message)
                            : _content(context, controller, state),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _topBar(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 12, 0),
      child: Row(
        children: [
          IconButton(
            icon: const Icon(Icons.close_rounded),
            color: AppColors.textSecondary,
            onPressed: () => Navigator.of(context).maybePop(false),
          ),
          const Spacer(),
          TextButton(
            onPressed: () =>
                Navigator.of(context).maybePop(false),
            child: const Text('稍后再说',
                style: TextStyle(color: AppColors.textSecondary)),
          ),
        ],
      ),
    );
  }

  Widget _content(
      BuildContext context, PaymentController controller, PaymentState state) {
    final recommendedCode = _recommendedCode(state.plans);
    final r = reason ?? const PaywallReason();
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 28),
      children: [
        _hero(r),
        const SizedBox(height: 22),
        _features(),
        const SizedBox(height: 24),
        const _SectionLabel('选择套餐'),
        const SizedBox(height: 12),
        ...state.plans.map((p) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: _PlanCard(
                plan: p,
                selected: p.planCode == state.selectedPlanCode,
                recommended: p.planCode == recommendedCode,
                onTap: state.isProcessing
                    ? null
                    : () => controller.selectPlan(p.planCode),
              ),
            )),
        if (state.channels.length > 1) ...[
          const SizedBox(height: 8),
          _channelSelector(context, controller, state),
        ],
        if (state.message != null &&
            state.stage != PurchaseStage.processing &&
            state.stage != PurchaseStage.success) ...[
          const SizedBox(height: 12),
          Text(
            state.message!,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: state.stage == PurchaseStage.error
                  ? AppColors.danger
                  : AppColors.warning,
              fontSize: 13,
            ),
          ),
        ],
        const SizedBox(height: 20),
        GlowButton(
          label: _ctaLabel(state),
          icon: Icons.bolt_rounded,
          loading: state.isProcessing,
          onTap: state.isProcessing ? null : controller.purchase,
        ),
        const SizedBox(height: 12),
        Center(
          child: TextButton(
            onPressed: state.isProcessing ? null : controller.restore,
            child: const Text('恢复购买',
                style: TextStyle(color: AppColors.textSecondary)),
          ),
        ),
        const SizedBox(height: 8),
        SafetyNotice(
          level: SafetyNoticeLevel.info,
          message:
              'PRO 会员可在多设备同步。支付由所选渠道安全处理；'
              'Apple 内购通过 App Store 管理订阅与续费。如遇问题请使用「恢复购买」。',
        ),
      ],
    );
  }

  /// Web（v1 自助下单关闭）下的只读内容：保留卖点展示，但不渲染任何
  /// 真实下单 CTA、渠道选择、套餐选择或「恢复购买」入口，改为提示联系
  /// 管理员。与 native 购买流程完全隔离，不发起下单请求。
  Widget _webClosedContent(BuildContext context, PaywallReason r) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 28),
      children: [
        _hero(r),
        const SizedBox(height: 22),
        _features(),
        const SizedBox(height: 24),
        _closedNotice(),
      ],
    );
  }

  Widget _closedNotice() {
    return HudCard(
      cornerColor: AppColors.warning,
      glow: false,
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.lock_outline_rounded,
                  size: 20, color: AppColors.warning),
              const SizedBox(width: 8),
              Text('自助开通暂未开放',
                  style: AppTheme.display(15, weight: FontWeight.w700)),
            ],
          ),
          const SizedBox(height: 10),
          const Text(
            'PRO 暂未开放自助开通，请联系管理员',
            style: TextStyle(
              color: AppColors.textSecondary,
              fontSize: 13,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }

  String _ctaLabel(PaymentState state) {
    if (state.isProcessing) return '处理中…';
    if (!isClientChannelReady(state.channel)) {
      return '${paymentChannelLabel(state.channel)} · 即将上线';
    }
    return '立即开通 PRO';
  }

  String? _recommendedCode(List<PaymentPlan> plans) {
    if (plans.any((p) => p.planCode.contains('year'))) {
      return plans
          .firstWhere(
            (p) => p.planCode.contains('year'),
            orElse: () => plans.first,
          )
          .planCode;
    }
    return plans.isNotEmpty ? plans.first.planCode : null;
  }

  Widget _hero(PaywallReason reason) {
    final exhausted = reason.isQuotaExhausted;
    final featureLabel = reason.featureLabel(source);
    // 共享池口径：标题统一说「本月免费次数已用完」，不再按功能命名；
    // 副标题点出刚才触发的操作，但明确额度是共享的同一个。
    final title = exhausted
        ? '本月免费次数已用完'
        : '解锁 AI 私教全部能力';
    final subtitle = exhausted
        ? (featureLabel != null
            ? '刚才的「$featureLabel」已计入本月共享额度，开通 PRO 不限次'
            : '体态评估与 AI 计划共享月度额度，开通 PRO 不限次')
        : '无限生成专属计划 · 体态拍照评估 · 持续训练追踪';
    return HudCard(
      cornerColor: exhausted ? AppColors.hot : AppColors.energy,
      glow: true,
      padding: const EdgeInsets.all(22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              DataTag(
                label: 'TIER',
                value: 'PRO',
                color: AppColors.hot,
              ),
              const Spacer(),
              Icon(
                exhausted ? Icons.flash_on_rounded : Icons.auto_awesome_rounded,
                color: AppColors.energy,
                size: 22,
              ),
            ],
          ),
          const SizedBox(height: 16),
          Text(
            title,
            style: AppTheme.display(24, weight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text(
            subtitle,
            style: const TextStyle(
                fontFamily: 'monospace',
                color: AppColors.textSecondary,
                fontSize: 12,
                height: 1.5),
          ),
          if (exhausted && reason.resetAt != null) ...[
            const SizedBox(height: 10),
            Row(
              children: [
                const Icon(Icons.schedule_rounded,
                    size: 13, color: AppColors.textMuted),
                const SizedBox(width: 5),
                Text(
                  '免费额度于 ${_formatReset(reason.resetAt!)} 重置',
                  style: const TextStyle(
                      fontFamily: 'monospace',
                      color: AppColors.textMuted,
                      fontSize: 11),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  String _formatReset(DateTime dt) {
    final local = dt.toLocal();
    final m = local.month.toString().padLeft(2, '0');
    final d = local.day.toString().padLeft(2, '0');
    return '${local.year}-$m-$d';
  }

  Widget _features() {
    final items = [
      (Icons.auto_awesome_rounded, 'AI 专属训练计划', '根据你的档案持续生成与迭代'),
      (Icons.camera_alt_rounded, '体态拍照评估', '上传照片，获取增肌/减脂/康复方向'),
      (Icons.track_changes_rounded, '训练追踪', '记录每组每组，量化进步'),
      (Icons.shield_outlined, '安全提示', '结合伤病与风险等级给出建议'),
    ];
    return Column(
      children: items
          .map((it) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(
                  children: [
                    Container(
                      width: 36,
                      height: 36,
                      decoration: BoxDecoration(
                        color: AppColors.energy.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(
                            color: AppColors.energy.withValues(alpha: 0.3)),
                      ),
                      child: Icon(it.$1, size: 18, color: AppColors.energy),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(it.$2,
                              style: const TextStyle(
                                  fontSize: 14, fontWeight: FontWeight.w700)),
                          const SizedBox(height: 2),
                          Text(it.$3,
                              style: const TextStyle(
                                  color: AppColors.textSecondary,
                                  fontSize: 12)),
                        ],
                      ),
                    ),
                  ],
                ),
              ))
          .toList(),
    );
  }

  Widget _channelSelector(
      BuildContext context, PaymentController controller, PaymentState state) {
    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: 8,
      runSpacing: 8,
      children: [
        const Padding(
          padding: EdgeInsets.only(right: 4),
          child: Text('支付渠道',
              style:
                  TextStyle(color: AppColors.textSecondary, fontSize: 12)),
        ),
        ...state.channels.map((c) {
          final selected = c == state.channel;
          final ready = isClientChannelReady(c);
          return ChoiceChip(
            label: Text(ready
                ? paymentChannelLabel(c)
                : '${paymentChannelLabel(c)} · 即将上线'),
            selected: selected,
            onSelected: (_) {
              if (!ready) {
                ScaffoldMessenger.of(context)
                  ..clearSnackBars()
                  ..showSnackBar(SnackBar(
                    content: Text(
                        '${paymentChannelLabel(c)}支付筹备中，即将上线，敬请期待'),
                    behavior: SnackBarBehavior.floating,
                  ));
                return;
              }
              controller.selectChannel(c);
            },
            selectedColor: AppColors.energy.withValues(alpha: 0.2),
            labelStyle: TextStyle(
              color: selected
                  ? AppColors.energy
                  : (ready
                      ? AppColors.textSecondary
                      : AppColors.textMuted),
              fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
              fontSize: 12,
            ),
            side: BorderSide(
              color: selected ? AppColors.energy : AppColors.border,
            ),
            backgroundColor: Colors.transparent,
            showCheckmark: false,
          );
        }),
      ],
    );
  }

  Widget _loadError(PaymentController controller, String? message) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_rounded,
                size: 48, color: AppColors.textMuted),
            const SizedBox(height: 12),
            Text(message ?? '套餐加载失败，请检查网络',
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppColors.textSecondary)),
            const SizedBox(height: 16),
            OutlinedButton(
              onPressed: controller.load,
              child: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String text;
  const _SectionLabel(this.text);
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(text,
            style: AppTheme.display(15, weight: FontWeight.w700)),
        const SizedBox(width: 8),
        const Text('// PLANS',
            style: TextStyle(
                fontFamily: 'monospace',
                color: AppColors.textMuted,
                fontSize: 11)),
      ],
    );
  }
}

class _PlanCard extends StatelessWidget {
  final PaymentPlan plan;
  final bool selected;
  final bool recommended;
  final VoidCallback? onTap;
  const _PlanCard({
    required this.plan,
    required this.selected,
    required this.recommended,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color = recommended ? AppColors.hot : AppColors.energy;
    final isYear = plan.durationDays >= 100;
    final monthlyEquivalent = plan.amount / (plan.durationDays / 30.0);

    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: HudCard(
        cornerColor: selected ? color : AppColors.borderBright,
        glow: selected,
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(plan.title,
                      style: AppTheme.display(16, weight: FontWeight.w700)),
                ),
                if (recommended)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 10, vertical: 3),
                    decoration: BoxDecoration(
                      gradient: AppColors.hotGradient,
                      borderRadius: BorderRadius.circular(AppRadius.pill),
                    ),
                    child: const Text('最划算',
                        style: TextStyle(
                            color: Colors.white,
                            fontSize: 11,
                            fontWeight: FontWeight.w800)),
                  ),
                const SizedBox(width: 8),
                _RadioMark(selected: selected, color: color),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(_formatPrice(plan.amount, plan.currency),
                    style: AppTheme.display(26,
                        weight: FontWeight.w800,
                        color: selected ? color : AppColors.textPrimary)),
                const SizedBox(width: 6),
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    isYear
                        ? '/ ${plan.durationDays ~/ 30} 个月'
                        : '/ ${plan.durationDays} 天',
                    style: const TextStyle(
                        color: AppColors.textSecondary, fontSize: 12),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              isYear
                  ? '折合 ${_formatPrice(monthlyEquivalent, plan.currency)} / 月'
                  : '每天约 ${_formatPrice(plan.amountPerDay, plan.currency)}',
              style: TextStyle(
                  fontFamily: 'monospace',
                  color: AppColors.textMuted,
                  fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }

  String _formatPrice(double amount, String currency) {
    final symbol = currency == 'CNY' ? '¥' : '$currency ';
    final text = amount == amount.roundToDouble()
        ? amount.toStringAsFixed(0)
        : amount.toStringAsFixed(1);
    return '$symbol$text';
  }
}

class _RadioMark extends StatelessWidget {
  final bool selected;
  final Color color;
  const _RadioMark({required this.selected, required this.color});
  @override
  Widget build(BuildContext context) {
    return Container(
      width: 22,
      height: 22,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: selected ? color : AppColors.borderBright, width: 2),
      ),
      child: selected
          ? Center(
              child: Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: color,
                  boxShadow: [BoxShadow(color: color, blurRadius: 8)],
                ),
              ),
            )
          : null,
    );
  }
}
