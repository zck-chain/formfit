import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';

class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _nickname = TextEditingController();
  bool _obscure = true;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _nickname.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    final ok = await ref.read(authProvider.notifier).register(
          _email.text.trim(),
          _password.text,
          _nickname.text.trim(),
        );
    if (ok && mounted) context.go('/profile');
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    return Scaffold(
      appBar: AppBar(leading: const BackButton()),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 28),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('创建账号',
                    style: TextStyle(
                        fontSize: 26, fontWeight: FontWeight.w800)),
                const SizedBox(height: 6),
                const Text('几步即可拥有你的 AI 私教',
                    style: TextStyle(color: AppColors.textSecondary)),
                const SizedBox(height: 32),
                if (auth.error != null)
                  Container(
                    margin: const EdgeInsets.only(bottom: 16),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.danger.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(AppRadius.sm),
                    ),
                    child: Text(auth.error!,
                        style: const TextStyle(color: AppColors.danger, fontSize: 13)),
                  ),
                TextField(
                  controller: _nickname,
                  decoration: const InputDecoration(
                      labelText: '昵称（选填）', prefixIcon: Icon(Icons.person_outline)),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  decoration: const InputDecoration(
                      labelText: '邮箱', prefixIcon: Icon(Icons.alternate_email)),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _password,
                  obscureText: _obscure,
                  decoration: InputDecoration(
                    labelText: '密码（至少 6 位）',
                    prefixIcon: const Icon(Icons.lock_outline),
                    suffixIcon: IconButton(
                      icon: Icon(_obscure
                          ? Icons.visibility_off_outlined
                          : Icons.visibility_outlined),
                      onPressed: () => setState(() => _obscure = !_obscure),
                    ),
                  ),
                ),
                const SizedBox(height: 28),
                ElevatedButton(
                  onPressed: auth.isLoading ? null : _submit,
                  child: auth.isLoading
                      ? const SizedBox(
                          width: 22, height: 22,
                          child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
                      : const Text('注 册'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
