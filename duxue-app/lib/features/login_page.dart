import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});
  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final email = TextEditingController();
  final password = TextEditingController();
  final name = TextEditingController();
  bool registering = false;
  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          child: SizedBox(
            width: 360,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.auto_awesome, size: 56),
                const SizedBox(height: 12),
                Text('读学', style: Theme.of(context).textTheme.headlineLarge),
                const SizedBox(height: 24),
                if (registering)
                  TextField(
                    controller: name,
                    decoration: const InputDecoration(labelText: '姓名'),
                  ),
                TextField(
                  controller: email,
                  keyboardType: TextInputType.emailAddress,
                  decoration: const InputDecoration(labelText: '邮箱'),
                ),
                TextField(
                  controller: password,
                  obscureText: true,
                  decoration: const InputDecoration(labelText: '密码（至少 8 位）'),
                ),
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: auth.isLoading
                      ? null
                      : () async {
                          try {
                            if (registering) {
                              await ref.read(authProvider.notifier).register(
                                    name.text,
                                    email.text,
                                    password.text,
                                  );
                            } else {
                              await ref
                                  .read(authProvider.notifier)
                                  .login(email.text, password.text);
                            }
                          } catch (error) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text(error.toString())),
                            );
                          }
                        },
                  child: Text(
                    auth.isLoading
                        ? '请稍候…'
                        : registering
                            ? '注册并登录'
                            : '登录',
                  ),
                ),
                TextButton(
                  onPressed: () => setState(() => registering = !registering),
                  child: Text(registering ? '已有账号？登录' : '没有账号？注册'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
