import 'observation_setup.dart';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:pretty_qr_code/pretty_qr_code.dart';
import '../core/models.dart';
import 'guardian_report_view.dart';
import 'guardian_question_page.dart';
import '../core/user_error_message.dart';
import '../providers.dart';
import '../shared/app_ui.dart';
import '../shared/app_version_label.dart';

class WardListPage extends ConsumerStatefulWidget {
  const WardListPage({super.key});
  @override
  ConsumerState<WardListPage> createState() => _WardListPageState();
}

class _WardListPageState extends ConsumerState<WardListPage> {
  int tab = 0;
  String? selectedWardId;
  @override
  Widget build(BuildContext context) {
    final wards = ref.watch(wardsProvider);
    final items = wards.valueOrNull ?? const <Ward>[];
    final selected = items.length == 1
        ? items.first
        : items.where((ward) => ward.id == selectedWardId).firstOrNull;
    return PopScope(
        canPop: tab == 0 && (items.length <= 1 || selected == null),
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop) {
            setState(() {
              if (tab != 0) {
                tab = 0;
              } else {
                selectedWardId = null;
              }
            });
          }
        },
        child: Scaffold(
          appBar: AppBar(
              centerTitle: false,
              leading: tab == 0 && selected != null && items.length > 1
                  ? IconButton(
                      tooltip: '全部孩子',
                      icon: const Icon(Icons.arrow_back),
                      onPressed: () => setState(() => selectedWardId = null))
                  : null,
              title: Text(tab == 0
                  ? selected?.displayName ?? '孩子'
                  : ['孩子', '问答', '我的'][tab]),
              actions: [
                if (tab == 0 && selected != null)
                  IconButton(
                      tooltip: '孩子设置',
                      icon: const Icon(Icons.settings_outlined),
                      onPressed: () => showWardSettings(context, selected.id)),
                if (tab == 0)
                  IconButton(
                      tooltip: '新增孩子',
                      icon: const Icon(Icons.person_add_alt_outlined),
                      onPressed: _create),
              ]),
          body: IndexedStack(index: tab, children: [
            wards.when(
                loading: () => const Center(child: CircularProgressIndicator()),
                error: (error, _) => Center(
                        child:
                            Column(mainAxisSize: MainAxisSize.min, children: [
                      Text('加载孩子档案失败：${userErrorMessage(error)}'),
                      TextButton(
                          onPressed: () => ref.invalidate(wardsProvider),
                          child: const Text('重新加载孩子档案')),
                    ])),
                data: (_) => selected == null
                    ? _children()
                    : GuardianReportView(
                        key: ValueKey(selected.id),
                        wardId: selected.id,
                        onTryQuestion: () => setState(() => tab = 1),
                        onInviteChild: () => showWardAppInviteDialog(
                            context, ref, selected.id,
                            wardName: selected.displayName))),
            GuardianQuestionPage(
                active: tab == 1,
                onStartWithChild: () => _startWithChild(items)),
            _profile(),
          ]),
          bottomNavigationBar: NavigationBar(
              selectedIndex: tab,
              onDestinationSelected: (value) => setState(() => tab = value),
              destinations: const [
                NavigationDestination(
                    icon: Icon(Icons.child_care_outlined),
                    selectedIcon: Icon(Icons.child_care),
                    label: '孩子'),
                NavigationDestination(
                    icon: Icon(Icons.chat_bubble_outline),
                    selectedIcon: Icon(Icons.chat_bubble),
                    label: '问答'),
                NavigationDestination(
                    icon: Icon(Icons.person_outline),
                    selectedIcon: Icon(Icons.person),
                    label: '我的'),
              ]),
        ));
  }

  Widget _children() {
    final wards = ref.watch(wardsProvider);
    return wards.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('加载孩子档案失败：${userErrorMessage(e)}')),
      data: (items) => Column(children: [
        Expanded(
            child: ListView(padding: const EdgeInsets.all(16), children: [
          if (items.isNotEmpty) ...[
            ...items.map((ward) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: _wardCard(ward))),
            OutlinedButton.icon(
                onPressed: _create,
                icon: const Icon(Icons.add),
                label: const Text('新增孩子档案')),
          ] else ...[
            AppCard(
                child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(children: [
                      const Icon(Icons.child_care_outlined,
                          size: 44, color: Color(0xff0f766e)),
                      const SizedBox(height: 12),
                      const Text('还没有孩子档案',
                          style: TextStyle(
                              fontWeight: FontWeight.w700, fontSize: 16)),
                      const SizedBox(height: 6),
                      const Text('创建档案后会自动生成 6 位绑定码，让孩子在学习设备上直接输入进入。',
                          textAlign: TextAlign.center,
                          style:
                              TextStyle(color: Colors.blueGrey, fontSize: 13)),
                      const SizedBox(height: 16),
                      FilledButton.icon(
                          onPressed: _create,
                          icon: const Icon(Icons.add),
                          label: const Text('新增孩子档案')),
                    ]))),
          ],
        ])),
      ]),
    );
  }

  Widget _wardCard(Ward ward) => AppCard(
        onTap: () => setState(() => selectedWardId = ward.id),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            CircleAvatar(
                backgroundColor: const Color(0xffdbeafe),
                child: Text(ward.displayName.characters.first)),
            const SizedBox(width: 12),
            Expanded(
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                  Text(ward.displayName,
                      style: const TextStyle(
                          fontWeight: FontWeight.w700, fontSize: 17)),
                  Text('${_gradeName(ward.gradeStage)} · 查看学习情况')
                ])),
            const Icon(Icons.chevron_right, color: Colors.blueGrey),
          ]),
          const SizedBox(height: 12),
          Row(children: [
            const Expanded(
              child: Text('学习记录与答疑过程',
                  style: TextStyle(color: Colors.blueGrey, fontSize: 13)),
            ),
            TextButton.icon(
              onPressed: () => showWardAppInviteDialog(
                context,
                ref,
                ward.id,
                wardName: ward.displayName,
              ),
              icon: const Icon(Icons.vpn_key_outlined, size: 16),
              label: const Text('获取绑定码'),
            ),
          ]),
        ]),
      );

  Widget _profile() => ListView(padding: const EdgeInsets.all(16), children: [
        const AppCard(
            child: ListTile(
                leading: CircleAvatar(child: Icon(Icons.person)),
                title: Text('家长账号'),
                subtitle: Text('管理账号与家庭'))),
        const SectionLabel('家庭'),
        const AppCard(
            child: ListTile(
                leading: Icon(Icons.group_outlined),
                title: Text('共管成员'),
                subtitle: Text('邀请其他监护人共同关注'))),
        const SizedBox(height: 20),
        OutlinedButton.icon(
            onPressed: () => ref.read(authProvider.notifier).logout(),
            icon: const Icon(Icons.logout),
            label: const Text('退出登录')),
        const SizedBox(height: 12),
        const AppVersionLabel(),
      ]);

  Future<void> _create() async {
    final controller = TextEditingController();
    var grade = 'primary';
    final name = await showModalBottomSheet<String>(
        context: context,
        isScrollControlled: true,
        builder: (context) => StatefulBuilder(
            builder: (context, setSheet) => Padding(
                padding: EdgeInsets.fromLTRB(
                    24, 24, 24, MediaQuery.viewInsetsOf(context).bottom + 24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Text('新增孩子档案',
                      style:
                          TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 16),
                  TextField(
                      controller: controller,
                      autofocus: true,
                      decoration: const InputDecoration(labelText: '孩子显示名称')),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                      // ignore: deprecated_member_use
                      value: grade,
                      decoration: const InputDecoration(labelText: '学段'),
                      items: const [
                        DropdownMenuItem(value: 'primary', child: Text('小学')),
                        DropdownMenuItem(value: 'middle', child: Text('初中')),
                        DropdownMenuItem(value: 'high', child: Text('高中')),
                      ],
                      onChanged: (value) => setSheet(() => grade = value!)),
                  const SizedBox(height: 12),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, controller.text),
                      child: const Text('创建并进入'))
                ]))));
    if (name?.trim().isEmpty ?? true) return;
    try {
      final ward = await ref.read(apiProvider).createWard(name!.trim(), grade);
      ref.invalidate(wardsProvider);
      if (mounted) {
        await showWardAppInviteDialog(
          context,
          ref,
          ward.id,
          wardName: ward.displayName,
        );
      }
    } catch (e) {
      if (mounted) showMessage(context, '创建失败：${userErrorMessage(e)}');
    }
  }

  Future<void> _startWithChild(List<Ward> wards) async {
    if (wards.isEmpty) {
      await _create();
      return;
    }
    Ward? selected = wards.length == 1 ? wards.first : null;
    selected ??= await showModalBottomSheet<Ward>(
        context: context,
        useSafeArea: true,
        builder: (context) => ListView(
                shrinkWrap: true,
                padding: const EdgeInsets.all(16),
                children: [
                  const ListTile(title: Text('让哪个孩子试试？')),
                  for (final ward in wards)
                    ListTile(
                        title: Text(ward.displayName),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => Navigator.pop(context, ward)),
                ]));
    if (!mounted || selected == null) return;
    await showWardAppInviteDialog(context, ref, selected.id,
        wardName: selected.displayName);
  }

  String _gradeName(String value) => switch (value) {
        'middle' => '初中',
        'high' => '高中',
        _ => '小学',
      };
}

class WardDetailPage extends ConsumerStatefulWidget {
  const WardDetailPage({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<WardDetailPage> createState() => _WardDetailPageState();
}

class _WardDetailPageState extends ConsumerState<WardDetailPage> {
  @override
  Widget build(BuildContext context) {
    final wards = ref.watch(wardsProvider).valueOrNull ?? const <Ward>[];
    final ward = wards.where((item) => item.id == widget.wardId).firstOrNull;
    return Scaffold(
      appBar: AppBar(title: Text(ward?.displayName ?? '孩子'), actions: [
        IconButton(
            tooltip: '孩子设置',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => showWardSettings(context, widget.wardId)),
      ]),
      body: GuardianReportView(wardId: widget.wardId),
    );
  }
}

Future<void> showWardSettings(BuildContext context, String wardId) =>
    showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        builder: (_) => FractionallySizedBox(
            heightFactor: 0.88, child: WardSettingsPage(wardId: wardId)));

class WardSettingsPage extends ConsumerStatefulWidget {
  const WardSettingsPage({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<WardSettingsPage> createState() => _WardSettingsPageState();
}

class _WardSettingsPageState extends ConsumerState<WardSettingsPage> {
  @override
  Widget build(BuildContext context) {
    final wards = ref.watch(wardsProvider).valueOrNull ?? const <Ward>[];
    final ward = wards.where((item) => item.id == widget.wardId).firstOrNull;
    return Scaffold(
        appBar: AppBar(
            title: const Text('孩子设置'),
            automaticallyImplyLeading: false,
            actions: [
              IconButton(
                  tooltip: '关闭设置',
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.pop(context))
            ]),
        body: _settings(ward));
  }

  Widget _settings(Ward? ward) =>
      ListView(padding: const EdgeInsets.all(16), children: [
        const SectionLabel('学生 App'),
        AppCard(
            onTap: _wardAppInvite,
            child: const ListTile(
                leading: Icon(Icons.phonelink_setup),
                title: Text('绑定/更换学生 App 设备'),
                subtitle: Text('生成一次性绑定码；换机后旧设备会退出'))),
        const SectionLabel('设备'),
        AppCard(
            onTap: () => showModalBottomSheet(
                context: context,
                isScrollControlled: true,
                builder: (_) => ObservationSetup(wardId: widget.wardId)),
            child: const ListTile(
                leading: Icon(Icons.visibility_outlined),
                title: Text('学习观察与晚间报告'))),
        AppCard(
            onTap: _invite,
            child: const ListTile(
                leading: Icon(Icons.qr_code),
                title: Text('添加读学Eye 设备'),
                subtitle: Text('用闲置 Android 手机扫码绑定'))),
        const SectionLabel('档案与进阶设置'),
        AppCard(
            onTap: () => context.go('/wards/${widget.wardId}/profiles'),
            child: ListTile(
                leading: const Icon(Icons.tune),
                title: const Text('分析配置'),
                subtitle: Text(ward?.analysisProfileId == null
                    ? '系统默认，不修改也能正常工作'
                    : '已使用自定义配置')))
      ]);

  Future<void> _wardAppInvite() async {
    final wards = ref.read(wardsProvider).valueOrNull ?? const <Ward>[];
    final ward = wards.where((item) => item.id == widget.wardId).firstOrNull;
    await showWardAppInviteDialog(
      context,
      ref,
      widget.wardId,
      wardName: ward?.displayName,
    );
  }

  Future<void> _invite() async {
    try {
      final invite = await ref.read(apiProvider).invite(widget.wardId);
      if (!mounted) return;
      await showDialog<void>(
          context: context,
          builder: (context) => AlertDialog(
                  title: const Text('用读学Eye 扫码绑定'),
                  content: SizedBox(
                      width: 250,
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                        PrettyQrView.data(
                            data: invite['qr_payload'],
                            decoration: const PrettyQrDecoration()),
                        const SizedBox(height: 12),
                        SelectableText(invite['invite_code'],
                            style: Theme.of(context).textTheme.headlineMedium),
                        const Text('10 分钟内一次性有效')
                      ])),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: const Text('完成'))
                  ]));
      ref.invalidate(devicesProvider(widget.wardId));
    } catch (e) {
      if (mounted) showMessage(context, '生成邀请码失败：${userErrorMessage(e)}');
    }
  }
}

Future<void> showWardAppInviteDialog(
  BuildContext context,
  WidgetRef ref,
  String wardId, {
  String? wardName,
}) async {
  try {
    final invite = await ref.read(apiProvider).wardInvite(wardId);
    if (!context.mounted) return;
    final title = wardName == null || wardName.trim().isEmpty
        ? '学生 App 绑定码'
        : '${wardName.trim()} · 学生 App 绑定码';
    await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
                title: Text(title),
                content: Column(mainAxisSize: MainAxisSize.min, children: [
                  SelectableText(invite['invite_code'] as String,
                      style: Theme.of(dialogContext).textTheme.headlineMedium),
                  const SizedBox(height: 10),
                  const Text(
                      '请在孩子的手机或平板上打开「读学」，选择【我是孩子】并输入此 6 位码（10 分钟内有效；换机后旧设备会自动退出）。'),
                ]),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(dialogContext),
                      child: const Text('完成'))
                ]));
  } catch (error) {
    if (context.mounted) {
      showMessage(context, '生成学生 App 绑定码失败：${userErrorMessage(error)}');
    }
  }
}
