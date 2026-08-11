import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../providers/auth_provider.dart';
import '../../providers/membership_provider.dart';
import '../../theme/app_theme.dart';
import '../../features/paywall/paywall_screen.dart';

class ProfileTab extends ConsumerWidget {
  const ProfileTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final membership = ref.watch(membershipProvider).valueOrNull;
    final user = auth.user;
    final profile = auth.profile;
    final isPro = membership?.isPro ?? false;

    return Scaffold(
      appBar: AppBar(title: const Text('我的')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 用户卡
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFF0E1114), Color(0xFF1F2A30)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(AppRadius.lg),
            ),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 30,
                  backgroundColor: AppColors.primary,
                  child: Text(
                    (user?.nickname ?? user?.email ?? 'U')
                        .substring(0, 1)
                        .toUpperCase(),
                    style: const TextStyle(
                        color: Colors.black,
                        fontSize: 24,
                        fontWeight: FontWeight.w700),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        user?.nickname ?? user?.email.split('@').first ?? '训练者',
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 18,
                            fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 4),
                      Text(user?.email ?? '',
                          style: const TextStyle(
                              color: Colors.white54, fontSize: 12)),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),

          // 身体数据快捷展示
          if (profile != null)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: _cardDecoration(context),
              child: Column(
                children: [
                  _dataRow('目标', profile.goal ?? '未设置'),
                  const Divider(height: 20),
                  _dataRow('身高',
                      profile.heightCm != null ? '${profile.heightCm!.toStringAsFixed(0)} cm' : '未设置'),
                  _dataRow('体重',
                      profile.weightKg != null ? '${profile.weightKg!.toStringAsFixed(0)} kg' : '未设置'),
                  _dataRow('BMI', profile.bmi?.toStringAsFixed(1) ?? '—'),
                  _dataRow('每周训练', '${profile.daysPerWeek ?? '—'} 天'),
                ],
              ),
            ),

          const SizedBox(height: 8),
          _MenuItem(
            icon: Icons.person_outline,
            label: '编辑身体档案',
            onTap: () => context.push('/profile'),
          ),
          _MenuItem(
            icon: isPro ? Icons.verified_rounded : Icons.credit_card_outlined,
            label: '会员中心',
            trailing: _ProBadge(active: isPro),
            onTap: () {
              PaywallScreen.push<bool>(context, source: 'profile').then((ok) {
                if (ok == true && context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('PRO 已开通')),
                  );
                }
              });
            },
          ),
          _MenuItem(
            icon: Icons.security_outlined,
            label: '隐私与安全',
            onTap: () {},
          ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: () async {
              await ref.read(authProvider.notifier).logout();
              if (context.mounted) context.go('/login');
            },
            icon: const Icon(Icons.logout, color: AppColors.danger),
            label: const Text('退出登录', style: TextStyle(color: AppColors.danger)),
            style: OutlinedButton.styleFrom(
              side: const BorderSide(color: Color(0xFFEDEFF2)),
              minimumSize: const Size(double.infinity, 50),
            ),
          ),
        ],
      ),
    );
  }

  BoxDecoration _cardDecoration(BuildContext context) => BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(
            color: Theme.of(context).brightness == Brightness.dark
                ? AppColors.trainingBorder
                : const Color(0xFFEDEFF2)),
      );

  Widget _dataRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: AppColors.textSecondary)),
          Text(value,
              style: const TextStyle(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

class _MenuItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final Widget? trailing;
  final VoidCallback onTap;
  const _MenuItem({
    required this.icon,
    required this.label,
    this.trailing,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(
            color: Theme.of(context).brightness == Brightness.dark
                ? AppColors.trainingBorder
                : const Color(0xFFEDEFF2)),
      ),
      child: ListTile(
        leading: Icon(icon, color: AppColors.textPrimary),
        title: Text(label),
        trailing: trailing ??
            const Icon(Icons.chevron_right, color: AppColors.textMuted),
        onTap: onTap,
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md)),
      ),
    );
  }
}

class _ProBadge extends StatelessWidget {
  final bool active;
  const _ProBadge({this.active = false});
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        gradient: active ? AppColors.energyGradient : null,
        color: active ? null : AppColors.cardHover,
        borderRadius: BorderRadius.circular(6),
        border: active ? null : Border.all(color: AppColors.borderBright),
      ),
      child: Text(active ? 'PRO' : 'FREE',
          style: TextStyle(
              color: active ? Colors.black : AppColors.textSecondary,
              fontSize: 11,
              fontWeight: FontWeight.w700)),
    );
  }
}
