import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:pretty_qr_code/pretty_qr_code.dart';
import '../core/models.dart';
import '../core/voice_transcription_service.dart';
import '../providers.dart';
import '../shared/app_ui.dart';

class WardListPage extends ConsumerStatefulWidget {
  const WardListPage({super.key});
  @override
  ConsumerState<WardListPage> createState() => _WardListPageState();
}

class _WardListPageState extends ConsumerState<WardListPage> {
  int tab = 0;
  @override
  Widget build(BuildContext context) {
    final titles = ['孩子', '决策', '我的'];
    return Scaffold(
      appBar: AppBar(
          title:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(titles[tab]),
        Text(
            tab == 0
                ? '我的家庭'
                : tab == 1
                    ? '待你回应的事项'
                    : '账号与家庭',
            style: Theme.of(context).textTheme.labelSmall)
      ])),
      body: switch (tab) {
        0 => _children(),
        1 => _decisions(),
        _ => _profile()
      },
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (value) => setState(() => tab = value),
        destinations: const [
          NavigationDestination(
              icon: Icon(Icons.child_care_outlined),
              selectedIcon: Icon(Icons.child_care),
              label: '孩子'),
          NavigationDestination(
              icon: Icon(Icons.volunteer_activism_outlined),
              selectedIcon: Icon(Icons.volunteer_activism),
              label: '决策'),
          NavigationDestination(
              icon: Icon(Icons.person_outline),
              selectedIcon: Icon(Icons.person),
              label: '我的')
        ],
      ),
    );
  }

  Widget _children() {
    final wards = ref.watch(wardsProvider);
    return wards.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('加载孩子档案失败：$e')),
      data: (items) => ListView(padding: const EdgeInsets.all(16), children: [
        FilledButton.icon(
            onPressed: () => _transfer(items),
            icon: const Icon(Icons.add),
            label: const Text('传递作业、通知或留言')),
        const SectionLabel('我的孩子'),
        if (items.isEmpty)
          const AppCard(
              child: Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(child: Text('还没有孩子档案，创建后即可传递任务和绑定读学Eye。')))),
        ...items.map((ward) => Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: _wardCard(ward))),
        OutlinedButton.icon(
            onPressed: _create,
            icon: const Icon(Icons.add),
            label: const Text('新增孩子档案')),
      ]),
    );
  }

  Widget _wardCard(Ward ward) => AppCard(
        onTap: () => context.go('/wards/${ward.id}'),
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
                  Text('${_gradeName(ward.gradeStage)} · 查看今日计划与成长报告')
                ])),
            const Icon(Icons.chevron_right)
          ]),
          const SizedBox(height: 12),
          const StatusPill(text: '读学Eye 状态将在详情查看', color: Colors.green),
        ]),
      );

  Widget _decisions() =>
      ListView(padding: const EdgeInsets.all(16), children: const [
        Text('系统只在需要你回应时提醒；你可以提出建议，但不能直接改写孩子确认的计划。'),
        SectionLabel('待回应'),
        AppCard(
            child: ListTile(
                leading: Icon(Icons.chat_bubble_outline),
                title: Text('今晚怎么聊'),
                subtitle: Text('孩子完成自我总结后，这里会出现基于事实的沟通建议。'))),
      ]);

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
      await ref.read(apiProvider).createWard(name!.trim(), grade);
      ref.invalidate(wardsProvider);
    } catch (e) {
      if (mounted) showMessage(context, '创建失败：$e');
    }
  }

  String _gradeName(String value) => switch (value) {
        'middle' => '初中',
        'high' => '高中',
        _ => '小学',
      };

  Future<void> _transfer(List<Ward> wards) async {
    final task = TextEditingController();
    final voice = VoiceTranscriptionService(
      baseUrl: apiBaseUrl,
      tokens: ref.read(tokenStorageProvider),
    );
    Timer? recordingLimit;
    var recording = false;
    var sending = false;
    var readyToConfirm = false;
    final history = <Map<String, dynamic>>[];
    var candidates = <Map<String, dynamic>>[];
    final attachments = <String>[];
    Future<void> stopVoice(StateSetter setSheet) async {
      if (!recording) return;
      recordingLimit?.cancel();
      recordingLimit = null;
      setSheet(() => recording = false);
      await voice.commit();
    }

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (_, setSheet) => Padding(
          padding: EdgeInsets.fromLTRB(
              12, 20, 12, MediaQuery.viewInsetsOf(sheetContext).bottom + 16),
          child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('传递任务',
                    style:
                        TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                const Text('说清任务和孩子；归属不明确时，我会先问你。'),
                const SizedBox(height: 10),
                if (history.isEmpty)
                  const Text('例如：小宇明天交数学练习册第 12 页；小雨朗读英语课文。'),
                ...history.map((message) => Align(
                      alignment: message['role'] == 'guardian'
                          ? Alignment.centerRight
                          : Alignment.centerLeft,
                      child: Container(
                        margin: const EdgeInsets.only(top: 8),
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: message['role'] == 'guardian'
                              ? Theme.of(sheetContext)
                                  .colorScheme
                                  .primaryContainer
                              : Theme.of(sheetContext)
                                  .colorScheme
                                  .surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(message['content'] as String),
                      ),
                    )),
                if (candidates.isNotEmpty)
                  AppCard(
                      child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                        const Text('当前整理的任务',
                            style: TextStyle(fontWeight: FontWeight.w700)),
                        ...candidates.map((item) {
                          final ward = wards
                              .where((value) => value.id == item['ward_id'])
                              .firstOrNull;
                          final due = item['due_date'] == null
                              ? ''
                              : ' · ${item['due_date']}';
                          return Padding(
                              padding: const EdgeInsets.only(top: 4),
                              child: Text(
                                  '${ward?.displayName ?? '待确认'}：${item['title']}$due'));
                        }),
                      ])),
                const SizedBox(height: 12),
                Row(children: [
                  GestureDetector(
                    onLongPressStart: (_) async {
                      if (recording || sending) return;
                      try {
                        await voice.start(
                          onPartial: (text) => setSheet(() {
                            task.value = TextEditingValue(
                              text: text,
                              selection:
                                  TextSelection.collapsed(offset: text.length),
                            );
                          }),
                          onFinal: (text) => setSheet(() {
                            recordingLimit?.cancel();
                            recordingLimit = null;
                            recording = false;
                            task.value = TextEditingValue(
                              text: text,
                              selection:
                                  TextSelection.collapsed(offset: text.length),
                            );
                          }),
                          onError: (message) {
                            if (!sheetContext.mounted) return;
                            setSheet(() => recording = false);
                            recordingLimit?.cancel();
                            showMessage(context, message);
                          },
                        );
                        if (!sheetContext.mounted) return;
                        setSheet(() {
                          recording = true;
                        });
                        recordingLimit =
                            Timer(const Duration(seconds: 60), () async {
                          await stopVoice(setSheet);
                          if (!sheetContext.mounted) return;
                          showMessage(sheetContext, '最长可录 60 秒，已结束识别');
                        });
                      } catch (error) {
                        if (!sheetContext.mounted) return;
                        showMessage(sheetContext, '$error');
                      }
                    },
                    onLongPressEnd: (_) => stopVoice(setSheet),
                    onLongPressCancel: () async {
                      if (!recording) return;
                      recordingLimit?.cancel();
                      setSheet(() => recording = false);
                      await voice.cancel();
                    },
                    child: SizedBox(
                      width: 44,
                      height: 44,
                      child: Icon(
                        recording ? Icons.mic : Icons.mic_none,
                        color: recording ? Colors.red : null,
                      ),
                    ),
                  ),
                  Expanded(
                    child: AbsorbPointer(
                      absorbing: recording,
                      child: TextField(
                        controller: task,
                        minLines: 1,
                        maxLines: 4,
                        decoration: InputDecoration(
                          hintText:
                              recording ? '正在识别，松开后可编辑' : '输入作业、通知或给孩子的留言',
                          isDense: true,
                        ),
                      ),
                    ),
                  ),
                  IconButton(
                    constraints:
                        const BoxConstraints.tightFor(width: 44, height: 44),
                    padding: EdgeInsets.zero,
                    tooltip: '添加附件',
                    icon: const Icon(Icons.add_circle_outline),
                    onPressed: recording || sending
                        ? null
                        : () async {
                            final image = await ImagePicker().pickImage(
                                source: ImageSource.gallery, imageQuality: 85);
                            if (image == null || !sheetContext.mounted) return;
                            try {
                              final extension =
                                  image.name.split('.').last.toLowerCase();
                              if (!const {'jpg', 'jpeg', 'png', 'webp'}
                                  .contains(extension)) {
                                if (sheetContext.mounted) {
                                  showMessage(
                                      sheetContext, '暂只支持 JPG、PNG 或 WebP 图片');
                                }
                                return;
                              }
                              final key = await ref
                                  .read(apiProvider)
                                  .uploadTaskIntakeImage(
                                      await image.readAsBytes(), extension);
                              if (sheetContext.mounted) {
                                setSheet(() => attachments.add(key));
                                showMessage(sheetContext, '已添加图片，发送后我会帮你整理');
                              }
                            } catch (_) {
                              if (sheetContext.mounted) {
                                showMessage(sheetContext, '图片上传失败，请重试');
                              }
                            }
                          },
                  ),
                ]),
                const SizedBox(height: 12),
                Row(children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: recording || sending
                          ? null
                          : () async {
                              if (task.text.trim().isEmpty &&
                                  attachments.isEmpty) {
                                return;
                              }
                              final content = task.text.trim();
                              setSheet(() => sending = true);
                              try {
                                final result = await ref
                                    .read(apiProvider)
                                    .respondToTaskIntake(
                                      content: content,
                                      history: history,
                                      tasks: candidates,
                                      attachmentKeys: attachments,
                                    );
                                if (!sheetContext.mounted) return;
                                setSheet(() {
                                  history.add({
                                    'role': 'guardian',
                                    'content':
                                        content.isEmpty ? '我添加了一张图片' : content
                                  });
                                  history.add({
                                    'role': 'assistant',
                                    'content':
                                        result['assistant_text'] as String
                                  });
                                  candidates = (result['tasks'] as List)
                                      .map((value) => Map<String, dynamic>.from(
                                          value as Map))
                                      .toList();
                                  readyToConfirm =
                                      result['ready_to_confirm'] as bool? ??
                                          false;
                                  task.clear();
                                });
                              } catch (_) {
                                if (sheetContext.mounted) {
                                  showMessage(sheetContext, '暂时无法整理任务，请重试');
                                }
                              } finally {
                                if (sheetContext.mounted) {
                                  setSheet(() => sending = false);
                                }
                              }
                            },
                      child: Text(sending ? '正在整理…' : '发送'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: FilledButton(
                      onPressed: !readyToConfirm || recording || sending
                          ? null
                          : () async {
                              setSheet(() => sending = true);
                              try {
                                await ref
                                    .read(apiProvider)
                                    .confirmTaskIntake(candidates, attachments);
                                if (sheetContext.mounted) {
                                  Navigator.pop(sheetContext);
                                }
                                if (mounted) {
                                  showMessage(context, '已传递，等待孩子确认安排');
                                }
                              } catch (_) {
                                if (sheetContext.mounted) {
                                  showMessage(sheetContext, '确认失败，请检查后重试');
                                }
                              } finally {
                                if (sheetContext.mounted) {
                                  setSheet(() => sending = false);
                                }
                              }
                            },
                      child: const Text('确认传递'),
                    ),
                  ),
                ]),
              ]),
        ),
      ),
    );
    recordingLimit?.cancel();
    await voice.dispose();
    if (attachments.isNotEmpty) {
      try {
        await ref.read(apiProvider).cleanupTaskIntake(attachments);
      } catch (_) {}
    }
    task.dispose();
  }
}

class WardDetailPage extends ConsumerStatefulWidget {
  const WardDetailPage({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<WardDetailPage> createState() => _WardDetailPageState();
}

class _WardDetailPageState extends ConsumerState<WardDetailPage> {
  int tab = 0;
  @override
  Widget build(BuildContext context) {
    final wards = ref.watch(wardsProvider).valueOrNull ?? const <Ward>[];
    final ward = wards.where((item) => item.id == widget.wardId).firstOrNull;
    return Scaffold(
        appBar: AppBar(title: Text(ward?.displayName ?? '孩子')),
        body: switch (tab) {
          0 => _today(),
          1 => _reports(),
          _ => _settings(ward)
        },
        bottomNavigationBar: NavigationBar(
            selectedIndex: tab,
            onDestinationSelected: (value) => setState(() => tab = value),
            destinations: const [
              NavigationDestination(
                  icon: Icon(Icons.today_outlined),
                  selectedIcon: Icon(Icons.today),
                  label: '今日'),
              NavigationDestination(
                  icon: Icon(Icons.auto_stories_outlined),
                  selectedIcon: Icon(Icons.auto_stories),
                  label: '报告'),
              NavigationDestination(
                  icon: Icon(Icons.settings_outlined),
                  selectedIcon: Icon(Icons.settings),
                  label: '设置')
            ]));
  }

  Widget _today() {
    final devices = ref.watch(devicesProvider(widget.wardId));
    return ListView(padding: const EdgeInsets.all(16), children: [
      devices.when(
          loading: () => const LinearProgressIndicator(),
          error: (_, __) =>
              const StatusPill(text: '设备状态暂不可用', color: Colors.orange),
          data: (items) => StatusPill(
              text: items.any((d) => d.status == 'online')
                  ? '读学Eye 在线 · 正在安静记录'
                  : '读学Eye 未在线',
              color: items.any((d) => d.status == 'online')
                  ? Colors.green
                  : Colors.orange)),
      const SectionLabel('今日计划'),
      const AppCard(
          child: ListTile(
              leading: Icon(Icons.check_circle_outline),
              title: Text('孩子确认的计划'),
              subtitle: Text('计划与任务进度由孩子自己安排；家长可以传递任务或留言。'))),
      const SizedBox(height: 10),
      AppCard(
          onTap: () => context.go('/wards/${widget.wardId}/story'),
          child: const ListTile(
              leading: Icon(Icons.add_task),
              title: Text('传递任务与查看今晚学习故事'),
              subtitle: Text('提交外部作业、生成孩子绑定码'))),
    ]);
  }

  Widget _reports() => ListView(padding: const EdgeInsets.all(16), children: [
        const AppCard(
            child: ListTile(
                leading: Icon(Icons.hourglass_top),
                title: Text('今日报告等待生成'),
                subtitle: Text('等孩子完成自我总结后，会生成今天的学习节奏与沟通建议。'))),
        const SectionLabel('过往报告'),
        AppCard(
            onTap: () => context.go('/wards/${widget.wardId}/report'),
            child: const ListTile(
                leading: Icon(Icons.article_outlined),
                title: Text('查看日报'),
                subtitle: Text('完成事实、学习节奏与沟通建议'))),
        const SizedBox(height: 10),
        AppCard(
            onTap: () => context.go('/wards/${widget.wardId}/trend'),
            child: const ListTile(
                leading: Icon(Icons.show_chart),
                title: Text('过去 7 天'),
                subtitle: Text('查看过往成长与学习节奏变化')))
      ]);

  Widget _settings(Ward? ward) =>
      ListView(padding: const EdgeInsets.all(16), children: [
        const SectionLabel('设备'),
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
      if (mounted) showMessage(context, '生成邀请码失败：$e');
    }
  }
}
