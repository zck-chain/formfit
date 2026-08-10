import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'providers/auth_provider.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    const ProviderScope(child: _Bootstrap()),
  );
}

/// 启动时先恢复登录态，再进入主 App
class _Bootstrap extends ConsumerStatefulWidget {
  const _Bootstrap();

  @override
  ConsumerState<_Bootstrap> createState() => _BootstrapState();
}

class _BootstrapState extends ConsumerState<_Bootstrap> {
  @override
  void initState() {
    super.initState();
    // 启动后异步恢复 token
    Future.microtask(() => ref.read(authProvider.notifier).bootstrap());
  }

  @override
  Widget build(BuildContext context) => const FormFitApp();
}
