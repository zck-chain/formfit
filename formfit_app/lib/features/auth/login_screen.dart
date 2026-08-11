import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/cyber/cyber_background.dart';
import '../../widgets/cyber/glow_button.dart';
import '../../widgets/cyber/hud_card.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController(text: 'demo@example.com');
  final _password = TextEditingController(text: '123456');
  bool _obscure = true;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    final ok = await ref
        .read(authProvider.notifier)
        .login(_email.text.trim(), _password.text);
    if (ok && mounted) context.go('/');
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    return Scaffold(
      body: CyberBackground(
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 40),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _logo(),
                  const SizedBox(height: 28),
                  _headline(),
                  const SizedBox(height: 28),
                  HudCard(
                    cornerColor: AppColors.energy,
                    glow: true,
                    padding: const EdgeInsets.all(22),
                    child: Column(
                      children: [
                        if (auth.error != null) _errorBox(auth.error!),
                        _field(
                          controller: _email,
                          label: 'EMAIL',
                          icon: Icons.alternate_email_rounded,
                        ),
                        const SizedBox(height: 14),
                        _field(
                          controller: _password,
                          label: 'PASSWORD',
                          icon: Icons.lock_outline_rounded,
                          obscure: _obscure,
                          suffix: IconButton(
                            icon: Icon(_obscure
                                ? Icons.visibility_off_outlined
                                : Icons.visibility_outlined),
                            color: AppColors.textMuted,
                            onPressed: () =>
                                setState(() => _obscure = !_obscure),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),
                  GlowButton(
                    label: 'INITIATE',
                    icon: Icons.bolt_rounded,
                    loading: auth.isLoading,
                    onTap: _submit,
                  ),
                  const SizedBox(height: 18),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Text('还没有账号？',
                          style: TextStyle(
                              color: AppColors.textSecondary, fontSize: 14)),
                      TextButton(
                        onPressed: () => context.push('/register'),
                        style: TextButton.styleFrom(
                            foregroundColor: AppColors.cyan),
                        child: const Text('立即注册',
                            style: TextStyle(fontWeight: FontWeight.w700)),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _logo() {
    return Row(
      children: [
        Container(
          width: 52, height: 52,
          decoration: BoxDecoration(
            gradient: AppColors.energyGradient,
            borderRadius: BorderRadius.circular(14),
            boxShadow: [
              BoxShadow(
                  color: AppColors.energy.withValues(alpha: 0.5),
                  blurRadius: 20,
                  offset: const Offset(0, 6)),
            ],
          ),
          child: const Icon(Icons.bolt_rounded, color: Colors.black, size: 30),
        ),
        const SizedBox(width: 14),
        Text('FormFit',
            style: AppTheme.display(28, weight: FontWeight.w800)),
      ],
    ).animate().fadeIn(duration: 500.ms).slideX(begin: -0.1);
  }

  Widget _headline() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('PUSH',
            style: AppTheme.display(46,
                weight: FontWeight.w800,
                color: AppColors.textPrimary)),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            ShaderMask(
              shaderCallback: (b) => const LinearGradient(
                colors: [AppColors.energy, AppColors.cyan],
              ).createShader(b),
              child: Text('YOUR LIMITS',
                  style: AppTheme.display(46,
                      weight: FontWeight.w800, color: Colors.white)),
            ),
            const Text('.',
                style: TextStyle(
                    color: AppColors.hot,
                    fontSize: 46,
                    fontWeight: FontWeight.w800)),
          ],
        ),
        const SizedBox(height: 10),
        const Text('// AI 私教已就绪，等待启动训练协议',
            style: TextStyle(
                fontFamily: 'monospace',
                color: AppColors.textSecondary,
                fontSize: 13)),
      ],
    ).animate().fadeIn(delay: 200.ms).slideY(begin: 0.1);
  }

  Widget _field({
    required TextEditingController controller,
    required String label,
    required IconData icon,
    bool obscure = false,
    Widget? suffix,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 11,
                color: AppColors.textMuted,
                letterSpacing: 1)),
        const SizedBox(height: 6),
        TextField(
          controller: controller,
          obscureText: obscure,
          style: const TextStyle(color: AppColors.textPrimary, fontSize: 15),
          keyboardType: label == 'EMAIL'
              ? TextInputType.emailAddress
              : TextInputType.text,
          decoration: InputDecoration(
            prefixIcon: Icon(icon, color: AppColors.textMuted, size: 20),
            suffixIcon: suffix,
          ),
        ),
      ],
    );
  }

  Widget _errorBox(String msg) {
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.danger.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(color: AppColors.danger.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded,
              color: AppColors.danger, size: 20),
          const SizedBox(width: 8),
          Expanded(
              child: Text(msg,
                  style: const TextStyle(
                      color: AppColors.danger, fontSize: 13))),
        ],
      ),
    );
  }
}
