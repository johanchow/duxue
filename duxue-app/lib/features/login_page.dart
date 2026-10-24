import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../providers.dart';
import 'day_story_pages.dart' show wardBindFailureMessage;

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});
  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final formKey = GlobalKey<FormState>();
  final email = TextEditingController();
  final code = TextEditingController();
  final name = TextEditingController();
  final bindingCode = TextEditingController();
  bool registering = false;
  bool wardMode = false;
  bool bindingLoading = false;
  bool codeSending = false;
  bool accountNotFound = false;
  int resendSeconds = 0;
  Timer? resendTimer;

  @override
  void dispose() {
    email.dispose();
    code.dispose();
    resendTimer?.cancel();
    name.dispose();
    bindingCode.dispose();
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
                  const SizedBox(height: 8),
                  SegmentedButton<bool>(
                    segments: const [
                      ButtonSegment(
                          value: true,
                          icon: Icon(Icons.child_care),
                          label: Text('我是孩子')),
                      ButtonSegment(
                          value: false,
                          icon: Icon(Icons.family_restroom),
                          label: Text('我是家长')),
                    ],
                    selected: {wardMode},
                    onSelectionChanged: (value) =>
                        setState(() => wardMode = value.first),
                  ),
                  const SizedBox(height: 24),
                  if (wardMode) ...[
                    const Text('用家长提供的 6 位绑定码进入自己的学习空间。',
                        textAlign: TextAlign.center),
                    const SizedBox(height: 16),
                    TextField(
                      key: const Key('ward-bind-code-input'),
                      controller: bindingCode,
                      enabled: !bindingLoading,
                      keyboardType: TextInputType.number,
                      textInputAction: TextInputAction.done,
                      maxLength: 6,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 22,
                        letterSpacing: 6,
                        fontWeight: FontWeight.w700,
                      ),
                      decoration: const InputDecoration(
                        labelText: '家长提供的 6 位绑定码',
                        hintText: '输入 6 位数字自动进入',
                      ),
                      onChanged: (value) {
                        if (value.trim().length == 6 && !bindingLoading) {
                          _bindWard();
                        }
                      },
                      onSubmitted: (_) => _bindWard(),
                    ),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      onPressed: bindingLoading ? null : _bindWard,
                      icon: const Icon(Icons.vpn_key_outlined),
                      label: Text(bindingLoading ? '绑定中…' : '绑定并进入'),
                    ),
                  ] else ...[
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
                      onChanged: (_) {
                        if (accountNotFound) {
                          setState(() => accountNotFound = false);
                        }
                      },
                      keyboardType: TextInputType.emailAddress,
                      textInputAction: TextInputAction.next,
                      autofillHints: const [
                        AutofillHints.username,
                        AutofillHints.email
                      ],
                      decoration: const InputDecoration(labelText: '邮箱'),
                      validator: _validateEmail,
                    ),
                    Row(children: [
                      Expanded(
                        child: TextFormField(
                          controller: code,
                          keyboardType: TextInputType.number,
                          textInputAction: TextInputAction.done,
                          maxLength: 6,
                          autofillHints: const [AutofillHints.oneTimeCode],
                          decoration: const InputDecoration(labelText: '邮箱验证码'),
                          validator: (value) => RegExp(r'^[0-9]{6}$')
                                  .hasMatch(value?.trim() ?? '')
                              ? null
                              : '请输入 6 位验证码',
                          onFieldSubmitted: (_) => _submit(),
                        ),
                      ),
                      const SizedBox(width: 8),
                      OutlinedButton(
                        onPressed:
                            codeSending || resendSeconds > 0 ? null : _sendCode,
                        child: Text(codeSending
                            ? '发送中…'
                            : resendSeconds > 0
                                ? '${resendSeconds}s 后重发'
                                : '获取验证码'),
                      ),
                    ]),
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
                    if (accountNotFound) ...[
                      const SizedBox(height: 8),
                      Text('该邮箱尚未注册，请先注册',
                          style: TextStyle(
                              color: Theme.of(context).colorScheme.error)),
                      TextButton(
                        onPressed: () => setState(() {
                          registering = true;
                          accountNotFound = false;
                        }),
                        child: const Text('去注册'),
                      ),
                    ],
                    TextButton(
                      onPressed: () => setState(() {
                        registering = !registering;
                        accountNotFound = false;
                      }),
                      child: Text(registering ? '已有账号？登录' : '没有账号？注册'),
                    ),
                  ],
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

  Future<void> _sendCode() async {
    final emailText = email.text.trim();
    final error = _validateEmail(emailText);
    if (error != null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error)));
      return;
    }
    setState(() => codeSending = true);
    try {
      await ref.read(apiProvider).sendEmailCode(emailText);
      if (!mounted) return;
      code.clear();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('新验证码已发送，请输入邮件中的最新验证码')),
      );
      resendTimer?.cancel();
      setState(() => resendSeconds = 60);
      resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
        if (!mounted) return timer.cancel();
        setState(() => resendSeconds--);
        if (resendSeconds <= 0) timer.cancel();
      });
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_messageFor(error))),
      );
    } finally {
      if (mounted) setState(() => codeSending = false);
    }
  }

  Future<void> _bindWard() async {
    final code = bindingCode.text.trim();
    if (code.length != 6) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请输入 6 位绑定码')),
      );
      return;
    }
    setState(() => bindingLoading = true);
    try {
      final id = await ref.read(apiProvider).bindWard(code);
      if (!mounted) return;
      ref.read(authProvider.notifier).enterWard(id);
      context.go('/ward-day/$id');
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(wardBindFailureMessage(error))),
      );
    } finally {
      if (mounted) setState(() => bindingLoading = false);
    }
  }

  Future<void> _submit() async {
    if (!(formKey.currentState?.validate() ?? false)) return;
    if (accountNotFound) setState(() => accountNotFound = false);
    try {
      if (registering) {
        await ref.read(authProvider.notifier).register(
              name.text.trim(),
              email.text.trim(),
              code.text.trim(),
            );
      } else {
        await ref.read(authProvider.notifier).login(
              email.text.trim(),
              code.text.trim(),
            );
      }
    } catch (error) {
      if (!mounted) return;
      if (!registering && _isAccountNotFound(error)) {
        setState(() => accountNotFound = true);
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_messageFor(error))),
      );
    }
  }

  bool _isAccountNotFound(Object error) {
    if (error is! DioException ||
        error.requestOptions.path != '/auth/login' ||
        error.response?.statusCode != 404) {
      return false;
    }
    final data = error.response?.data;
    return data is Map && data['detail'] == 'account not found';
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
        if (status == 400) return '验证码无效或已过期，请重新获取';
        if (status == 404) return '请求的服务暂不可用，请稍后重试';
        if (status == 429) return '请求过于频繁，请稍后再试';
        if (status == 401) return '登录失败，请重试';
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
