import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../providers.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});
  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final formKey = GlobalKey<FormState>();
  final email = TextEditingController();
  final password = TextEditingController();
  final name = TextEditingController();
  bool registering = false;

  @override
  void dispose() {
    email.dispose();
    password.dispose();
    name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          child: SizedBox(
            width: 360,
            child: Form(
              key: formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.auto_awesome, size: 56),
                  const SizedBox(height: 12),
                  Text('读学', style: Theme.of(context).textTheme.headlineLarge),
                  const SizedBox(height: 24),
                  if (registering)
                    TextFormField(
                      controller: name,
                      textInputAction: TextInputAction.next,
                      decoration: const InputDecoration(labelText: '姓名'),
                      validator: (value) =>
                          value == null || value.trim().isEmpty
                              ? '请输入姓名'
                              : null,
                    ),
                  TextFormField(
                    controller: email,
                    keyboardType: TextInputType.emailAddress,
                    textInputAction: TextInputAction.next,
                    autofillHints: const [
                      AutofillHints.username,
                      AutofillHints.email
                    ],
                    decoration: const InputDecoration(labelText: '邮箱'),
                    validator: _validateEmail,
                  ),
                  TextFormField(
                    controller: password,
                    obscureText: true,
                    textInputAction: TextInputAction.done,
                    autofillHints: const [AutofillHints.password],
                    decoration: const InputDecoration(labelText: '密码（至少 8 位）'),
                    validator: (value) {
                      if (value == null || value.isEmpty) return '请输入密码';
                      if (registering && value.length < 8) return '密码至少需要 8 位';
                      return null;
                    },
                    onFieldSubmitted: (_) => _submit(),
                  ),
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: auth.isLoading ? null : _submit,
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
                  TextButton.icon(
                    onPressed: () => context.go('/ward-bind'),
                    icon: const Icon(Icons.child_care),
                    label: const Text('我是学生，用绑定码进入'),
                  ),
                  if (kDebugMode) ...[
                    const SizedBox(height: 12),
                    SelectableText(
                      '测试服务：$apiBaseUrl',
                      textAlign: TextAlign.center,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  String? _validateEmail(String? value) {
    final email = value?.trim() ?? '';
    if (email.isEmpty) return '请输入邮箱';
    if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(email)) {
      return '请输入有效的邮箱地址';
    }
    return null;
  }

  Future<void> _submit() async {
    if (!(formKey.currentState?.validate() ?? false)) return;
    try {
      if (registering) {
        await ref.read(authProvider.notifier).register(
              name.text.trim(),
              email.text.trim(),
              password.text,
            );
      } else {
        await ref.read(authProvider.notifier).login(
              email.text.trim(),
              password.text,
            );
      }
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_messageFor(error))),
      );
    }
  }

  String _messageFor(Object error) {
    if (error is! DioException) return '操作失败，请稍后重试';
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.transformTimeout:
        return '连接服务超时，请检查网络或服务地址';
      case DioExceptionType.connectionError:
        return '无法连接服务，请检查网络或服务地址';
      case DioExceptionType.badResponse:
        final status = error.response?.statusCode;
        if (status == 401) return '邮箱或密码不正确';
        if (status == 409) return '该邮箱已注册，请直接登录';
        if (status == 422) return '提交的信息不符合要求，请检查后重试';
        if (status != null && status >= 500) return '服务暂时不可用，请稍后重试';
        return '请求失败，请稍后重试';
      case DioExceptionType.cancel:
      case DioExceptionType.badCertificate:
      case DioExceptionType.unknown:
        return '网络请求失败，请检查网络后重试';
    }
  }
}
