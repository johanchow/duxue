import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/user_error_message.dart';
import '../providers.dart';
import '../shared/app_ui.dart';

final _membersProvider = FutureProvider.autoDispose(
    (ref) => ref.watch(apiProvider).guardianMembers());

class GuardianMembersPage extends ConsumerStatefulWidget {
  const GuardianMembersPage({super.key});

  @override
  ConsumerState<GuardianMembersPage> createState() =>
      _GuardianMembersPageState();
}

class _GuardianMembersPageState extends ConsumerState<GuardianMembersPage> {
  bool _busy = false;

  Future<void> _change(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
      if (!mounted) return;
      ref.invalidate(_membersProvider);
      ref.invalidate(wardsProvider);
    } catch (error) {
      if (mounted) showMessage(context, '操作失败：${userErrorMessage(error)}');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirm(String title, String message, String label,
      Future<void> Function() action) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: Text(label)),
        ],
      ),
    );
    if (confirmed == true && mounted) await _change(action);
  }

  Future<void> _invite(String id, String name) async {
    var email = '';
    final address = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('邀请共管 $name'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('对方接受后，可以查看和编辑孩子档案、管理绑定与设备。'),
          TextField(
            autofocus: true,
            keyboardType: TextInputType.emailAddress,
            autocorrect: false,
            onChanged: (text) => email = text.trim(),
            decoration: const InputDecoration(labelText: '对方的登录邮箱'),
          ),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, email),
              child: const Text('发起邀请')),
        ],
      ),
    );
    if (address == null || !mounted) return;
    if (address.isEmpty) {
      showMessage(context, '请输入对方的登录邮箱');
      return;
    }
    await _change(() => ref.read(apiProvider).inviteGuardian(id, address));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('共管成员')),
        body: ref.watch(_membersProvider).when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => Center(
                child: TextButton(
                  onPressed: () => ref.invalidate(_membersProvider),
                  child: Text('加载失败，点击重试：${userErrorMessage(error)}'),
                ),
              ),
              data: (data) => _list(data),
            ),
      );

  Widget _list(Map<String, dynamic> data) {
    final api = ref.read(apiProvider);
    final incoming = (data['incoming'] as List).cast<Map<String, dynamic>>();
    final wards = (data['wards'] as List).cast<Map<String, dynamic>>();
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(wardsProvider);
        ref.invalidate(_membersProvider);
        await ref.read(_membersProvider.future);
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        children: [
          if (incoming.isNotEmpty) const SectionLabel('收到的邀请'),
          for (final item in incoming)
            ListTile(
              title: Text('${item['inviter']} 邀请你共管 ${item['ward_name']}'),
              subtitle: const Text('接受后可以查看和管理孩子档案'),
              trailing: TextButton(
                onPressed: _busy
                    ? null
                    : () => _change(
                        () => api.acceptGuardianInvite(item['id'] as String)),
                child: const Text('接受邀请'),
              ),
            ),
          if (wards.isEmpty && incoming.isEmpty) const Text('暂无孩子档案或共管邀请'),
          for (final ward in wards) ...[
            SectionLabel(ward['name'] as String),
            if (ward['can_manage'] == true)
              TextButton.icon(
                onPressed: _busy
                    ? null
                    : () =>
                        _invite(ward['id'] as String, ward['name'] as String),
                icon: const Icon(Icons.person_add_alt_outlined),
                label: const Text('邀请共管'),
              ),
            for (final member in ward['members'] as List)
              ListTile(
                title: Text(member['name'] as String),
                subtitle: Text(member['email'] as String),
                trailing: TextButton(
                  onPressed: _busy
                      ? null
                      : () => _confirm(
                            '移除共管成员',
                            '${member['name']} 将无法继续查看和管理 ${ward['name']} 的档案。',
                            '移除',
                            () => api.removeGuardian(
                                ward['id'] as String, member['id'] as String),
                          ),
                  child: const Text('移除'),
                ),
              ),
            for (final item in ward['pending'] as List)
              ListTile(
                title: Text(item['email'] as String),
                subtitle: const Text('待接受 · 邀请 24 小时有效'),
                trailing: TextButton(
                  onPressed: _busy
                      ? null
                      : () => _change(() => api.cancelGuardianInvite(
                          ward['id'] as String, item['id'] as String)),
                  child: const Text('取消邀请'),
                ),
              ),
            if (ward['can_leave'] == true)
              TextButton(
                onPressed: _busy
                    ? null
                    : () => _confirm(
                          '退出共管',
                          '退出后，你将无法继续查看和管理 ${ward['name']} 的档案。',
                          '退出共管',
                          () => api.removeGuardian(ward['id'] as String, 'me'),
                        ),
                child: const Text('退出共管'),
              ),
          ],
        ],
      ),
    );
  }
}
