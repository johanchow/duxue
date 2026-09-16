import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import '../providers.dart';
import '../shared/app_ui.dart';
import '../shared/voice_composer.dart';

String wardBindFailureMessage(Object error) {
  if (error is DioException) {
    return '绑定失败，请检查 6 位绑定码或网络后重试。';
  }
  // ApiClient.bindWard only reaches a non-network error after the server has
  // accepted the binding response, usually while persisting the local session.
  return '绑定请求已成功，但本机登录状态保存失败；请查看 Flutter 终端日志。';
}

class WardBindPage extends ConsumerStatefulWidget {
  const WardBindPage({super.key});
  @override
  ConsumerState<WardBindPage> createState() => _WardBindPageState();
}

class _WardBindPageState extends ConsumerState<WardBindPage> {
  final code = TextEditingController();
  bool loading = false;
  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('学生设备绑定')),
      body: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(children: [
            TextField(
                controller: code,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: const InputDecoration(labelText: '家长提供的 6 位绑定码')),
            const SizedBox(height: 20),
            FilledButton(
                onPressed: loading ? null : _bind,
                child: Text(loading ? '绑定中…' : '绑定并进入'))
          ])));
  Future<void> _bind() async {
    setState(() => loading = true);
    try {
      final id = await ref.read(apiProvider).bindWard(code.text.trim());
      if (mounted) {
        ref.read(authProvider.notifier).enterWard(id);
        context.go('/ward-day/$id');
      }
    } catch (error, stackTrace) {
      final detail = error is DioException
          ? 'HTTP ${error.response?.statusCode ?? 'network'}'
          : error.runtimeType.toString();
      debugPrint('Ward bind failed after submission: $detail');
      debugPrintStack(stackTrace: stackTrace);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(wardBindFailureMessage(error))));
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }
}

class GuardianStoryPage extends ConsumerStatefulWidget {
  const GuardianStoryPage({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<GuardianStoryPage> createState() => _GuardianStoryPageState();
}

class _GuardianStoryPageState extends ConsumerState<GuardianStoryPage> {
  final task = TextEditingController();
  Map<String, dynamic>? story;
  @override
  Widget build(BuildContext context) {
    final s = story;
    return Scaffold(
        appBar: AppBar(title: const Text('今晚的学习故事')),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          TextField(
              controller: task,
              decoration: const InputDecoration(labelText: '交给孩子的作业'),
              onSubmitted: (_) => _add()),
          FilledButton(onPressed: _add, child: const Text('交作业')),
          const SizedBox(height: 16),
          FilledButton.tonal(onPressed: _load, child: const Text('查看当晚事实报告')),
          if (s != null)
            Card(
                child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: s['status'] == 'locked'
                        ? const Text('孩子完成自评后，今晚报告会在这里出现。')
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                                Text(
                                    '学习用时：${(s['total_seconds'] as int) ~/ 60} 分钟'),
                                Text('答疑卡点：${s['stuck_points']} 个'),
                                const Text('沟通建议',
                                    style:
                                        TextStyle(fontWeight: FontWeight.bold)),
                                ...((s['communication_suggestions'] as List)
                                    .map((x) => Text('• $x')))
                              ])))
        ]));
  }

  Future<void> _add() async {
    if (task.text.trim().isEmpty) return;
    await ref
        .read(apiProvider)
        .createAssignment(widget.wardId, task.text.trim());
    task.clear();
  }

  Future<void> _load() async {
    final x = await ref
        .read(apiProvider)
        .guardianStory(widget.wardId, DateTime.now());
    if (mounted) setState(() => story = x);
  }
}

class WardDayPage extends ConsumerStatefulWidget {
  const WardDayPage({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<WardDayPage> createState() => _WardDayPageState();
}

class _WardDayPageState extends ConsumerState<WardDayPage> {
  List<dynamic> tasks = [];
  Map<String, dynamic>? plan, insight, profile;
  String? session;
  int tab = 0;
  final watch = Stopwatch();
  final planAttachments = <String>[];
  List<Map<String, dynamic>> planDraft = [];
  final planMessages = <Map<String, String>>[];
  String? companionThreadId;
  int? companionThreadVersion;
  String? planFeedback;
  String? failedPlanText;
  bool planSending = false;
  bool planListOpen = false;
  bool planChatOpen = false;
  String? chatSubject;
  final removedPoolTaskIds = <String>{};
  Timer? timer;
  int savedSeconds = 0;
  @override
  void initState() {
    super.initState();
    _load();
    _restoreCompanionThread();
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
          child: switch (tab) {
        0 => _home(context),
        1 => _growth(context),
        _ => _profile(context)
      }),
      bottomNavigationBar: NavigationBar(
          selectedIndex: tab,
          onDestinationSelected: (value) => setState(() => tab = value),
          destinations: const [
            NavigationDestination(
                icon: Icon(Icons.home_outlined),
                selectedIcon: Icon(Icons.home),
                label: '首页'),
            NavigationDestination(
                icon: Icon(Icons.eco_outlined),
                selectedIcon: Icon(Icons.eco),
                label: '成长'),
            NavigationDestination(
                icon: Icon(Icons.person_outline),
                selectedIcon: Icon(Icons.person),
                label: '我的')
          ]),
    );
  }

  Widget _home(BuildContext context) {
    final planned = (plan?['items'] as List? ?? const []).cast<dynamic>();
    final plannedAssignmentIds = planned
        .map((item) => item['assignment_id'])
        .whereType<String>()
        .toSet();
    final pool = tasks
        .where((item) =>
            !plannedAssignmentIds.contains(item['id']) &&
            !removedPoolTaskIds.contains(item['id']))
        .toList();
    return Stack(children: [
      ListView(padding: const EdgeInsets.fromLTRB(16, 14, 16, 156), children: [
        _homeGreeting(context),
        _contextHeader(plan?['status'] == 'confirmed' ? '已确认 · 今日计划' : '今日计划',
            action: planned.isEmpty ? null : _openPlanList, actionLabel: '全部'),
        if (planned.isEmpty)
          const _HomeEmptyCard(message: '今天还没有确认计划。可以在下方说说你想怎么安排。')
        else
          _planRail(planned),
        const SizedBox(height: 14),
        _contextHeader('待你决定', meta: '${pool.length} 项 · 左滑删除'),
        if (pool.isEmpty)
          const _HomeEmptyCard(message: '今天没有待定项了。想加任务，走下方统一入口。')
        else
          ...pool.map((item) => _poolTask(item as Map<String, dynamic>)),
        const Padding(
            padding: EdgeInsets.only(top: 8, left: 2, right: 2),
            child: Text('这些不会自动排进今天。左滑可移除；想调整安排，直接告诉读学。',
                style: TextStyle(fontSize: 12, color: Colors.blueGrey))),
        if (planned.isNotEmpty) ...[
          const SizedBox(height: 18),
          FilledButton.tonal(
              onPressed: _review, child: const Text('完成今日计划，先说说自己的感受')),
        ],
      ]),
      if (planListOpen) _planListOverlay(planned),
      if (planChatOpen) _planChatOverlay(),
      if (!planListOpen)
        Positioned(left: 16, right: 16, bottom: 12, child: _chatEntry()),
    ]);
  }

  Widget _homeGreeting(BuildContext context) => Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(
              '周${_weekday(DateTime.now())} · ${DateTime.now().month} 月 ${DateTime.now().day} 日',
              style: const TextStyle(fontSize: 12, color: Colors.blueGrey)),
          const SizedBox(height: 4),
          Text('晚上好，${profile?['display_name'] ?? '同学'}',
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 5),
          const Text('你先说，我来帮你记录和检查安排。',
              style: TextStyle(fontSize: 13, color: Colors.blueGrey)),
        ])),
      ]));

  Widget _contextHeader(String title,
          {String? meta, VoidCallback? action, String? actionLabel}) =>
      Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(children: [
            const Icon(Icons.circle, size: 7, color: Color(0xff0f766e)),
            const SizedBox(width: 8),
            Text(title.toUpperCase(),
                style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: Colors.blueGrey,
                    letterSpacing: 1)),
            const Spacer(),
            if (meta != null)
              Text(meta,
                  style: const TextStyle(fontSize: 12, color: Colors.blueGrey)),
            if (action != null)
              TextButton(onPressed: action, child: Text(actionLabel ?? '查看')),
          ]));

  Widget _planRail(List<dynamic> planned) => SizedBox(
      height: 116,
      child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: planned.length,
          separatorBuilder: (_, __) => const SizedBox(width: 8),
          itemBuilder: (_, index) {
            final item = planned[index] as Map<String, dynamic>;
            return SizedBox(
                width: 150,
                child: Card(
                    color: index == 0 ? const Color(0xfff0fdfa) : Colors.white,
                    child: InkWell(
                        borderRadius: BorderRadius.circular(16),
                        onTap: () => _openPlanChat(item['title'] as String),
                        child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(index == 0 ? '现在' : '稍后',
                                      style: const TextStyle(
                                          fontSize: 11,
                                          color: Colors.blueGrey)),
                                  const SizedBox(height: 4),
                                  Text(item['title'] as String,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                          fontWeight: FontWeight.w700)),
                                  const Spacer(),
                                  Text('约 ${item['planned_minutes'] ?? 30} 分钟',
                                      style: const TextStyle(
                                          fontSize: 11,
                                          color: Colors.blueGrey)),
                                ])))));
          }));

  Widget _poolTask(Map<String, dynamic> item) {
    final status = item['status'] as String? ?? 'open';
    return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Dismissible(
            key: ValueKey('pool-${item['id']}'),
            direction: DismissDirection.endToStart,
            background: Container(
                alignment: Alignment.centerRight,
                padding: const EdgeInsets.only(right: 22),
                decoration: BoxDecoration(
                    color: Colors.red.shade700,
                    borderRadius: BorderRadius.circular(16)),
                child: const Icon(Icons.delete_outline, color: Colors.white)),
            onDismissed: (_) {
              setState(() => removedPoolTaskIds.add(item['id'] as String));
              showMessage(context, '「${item['title']}」已从任务池移除');
            },
            child: AppCard(
                padding: EdgeInsets.zero,
                onTap: () => _taskTapped(item, false),
                child: Padding(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 13),
                    child: Row(children: [
                      const Icon(Icons.check_box_outline_blank,
                          color: Color(0xff94a3b8)),
                      const SizedBox(width: 12),
                      Expanded(
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                            Text(item['title'] as String,
                                style: const TextStyle(
                                    fontWeight: FontWeight.w700)),
                            Text(item['details'] as String? ?? '任务池 · 尚未安排',
                                style: const TextStyle(
                                    fontSize: 12, color: Colors.blueGrey)),
                          ])),
                      StatusPill(
                          text: status == 'active'
                              ? '进行中'
                              : status == 'paused'
                                  ? '已暂停'
                                  : '未安排',
                          color: status == 'open'
                              ? Colors.deepPurple
                              : status == 'paused'
                                  ? Colors.orange
                                  : brandBlue),
                    ])))));
  }

  Widget _chatEntry() => AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: VoiceComposer(
          baseUrl: apiBaseUrl,
          tokens: ref.read(tokenStorageProvider),
          telemetry: ref.read(telemetryProvider),
          holdToTalkText: '说出你的任何想法、问题、安排',
          helperText: '按住说话',
          enabled: !planSending,
          onTap: _openPlanChat,
          onBeforeRecording: () => ref.read(apiProvider).ensureValidAccess(),
          onPickImage: _pickPlanImage,
          onVoiceFinal: _onVoicePlanInput));

  Widget _planListOverlay(List<dynamic> planned) => _HomeOverlay(
      title: '今日计划',
      subtitle: '已确认 · 共 ${planned.length} 项 · 你说了算',
      onClose: () => setState(() => planListOpen = false),
      child: planned.isEmpty
          ? const Text('还没有确认计划。')
          : ListView.separated(
              shrinkWrap: true,
              itemCount: planned.length,
              separatorBuilder: (_, __) => const Divider(),
              itemBuilder: (_, index) {
                final item = planned[index] as Map<String, dynamic>;
                return ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: CircleAvatar(
                        radius: 14,
                        backgroundColor: const Color(0xffe6f4f1),
                        child: Text('${index + 1}',
                            style: const TextStyle(fontSize: 12))),
                    title: Text(item['title'] as String),
                    subtitle: Text('约 ${item['planned_minutes'] ?? 30} 分钟'),
                    onTap: () => setState(() {
                          planListOpen = false;
                          chatSubject = item['title'] as String;
                          planChatOpen = true;
                        }));
              }));

  Widget _planChatOverlay() => _HomeOverlay(
      title: '读学',
      subtitle: '你先说；我记录并检查冲突，确认后才生效。',
      onClose: () => setState(() => planChatOpen = false),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
            width: double.infinity,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
                color: const Color(0xfff0fdfa),
                borderRadius: BorderRadius.circular(12)),
            child: Text(_chatContext(),
                style:
                    const TextStyle(fontSize: 12, color: Color(0xff0f766e)))),
        const SizedBox(height: 14),
        const _ChatBubble(
            label: '读学 AI', text: '我不会替你排今天。你说想怎么安排，我帮你记下来，并检查有没有冲突。'),
        for (final message in planMessages) ...[
          const SizedBox(height: 10),
          _ChatBubble(label: message['label']!, text: message['content']!),
        ],
        if (planAttachments.isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('已添加 ${planAttachments.length} 张图片，读学会一起整理。',
              style: const TextStyle(fontSize: 12, color: Colors.blueGrey)),
        ],
        if (planSending) ...[
          const SizedBox(height: 14),
          const Center(child: CircularProgressIndicator()),
        ],
        if (failedPlanText != null) ...[
          const SizedBox(height: 10),
          Row(children: [
            const Expanded(
                child: Text('这条消息暂未送达。',
                    style: TextStyle(fontSize: 12, color: Colors.redAccent))),
            TextButton(
                onPressed: planSending
                    ? null
                    : () => _submitPlanInput(failedPlanText!),
                child: const Text('重试')),
          ]),
        ],
        if (planDraft.isNotEmpty) ...[
          const SizedBox(height: 14),
          AppCard(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                const Text('已记录（待你确认）',
                    style: TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                for (final item in planDraft)
                  Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text(
                          '• ${item['title']} · 约 ${item['planned_minutes']} 分钟')),
                const SizedBox(height: 8),
                Row(children: [
                  Expanded(
                      child: OutlinedButton(
                          onPressed: () =>
                              showMessage(context, '草稿还在，按住下方再说想改哪一段。'),
                          child: const Text('我再改一句'))),
                  const SizedBox(width: 8),
                  Expanded(
                      child: FilledButton(
                          onPressed: planSending ? null : _confirmPlanDraft,
                          child: const Text('确认这个计划'))),
                ])
              ]))
        ]
      ]));

  void _openPlanList() => setState(() {
        planChatOpen = false;
        planListOpen = true;
      });

  void _openPlanChat([String? subject]) => setState(() {
        planListOpen = false;
        chatSubject = subject;
        planChatOpen = true;
      });

  String _chatContext() {
    if (chatSubject != null) return '语境：关于「${chatSubject!}」——按住下方再说。';
    final count = (plan?['items'] as List? ?? const []).length;
    return '已知：今天已确认 $count 项计划；另有 ${tasks.length - removedPoolTaskIds.length} 项待你决定。';
  }

  Future<void> _onVoicePlanInput(String text) async {
    _openPlanChat();
    setState(() => planMessages.add({'label': '我', 'content': text}));
    await _submitPlanInput(text);
  }

  Widget _growth(BuildContext context) =>
      ListView(padding: const EdgeInsets.all(16), children: [
        const SectionLabel('今天'),
        if (insight == null)
          const AppCard(
              child: ListTile(
                  leading: Icon(Icons.edit_note),
                  title: Text('今天的反馈等待生成'),
                  subtitle: Text('完成今天的自我总结后，这里会出现你的感受和观察记录的对照。')))
        else
          AppCard(
              child: Padding(
                  padding: const EdgeInsets.all(4),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const ListTile(
                            leading: Icon(Icons.compare_arrows),
                            title: Text('你的感受与观察记录'),
                            subtitle: Text('先看自己的体感，再一起发现学习节奏。')),
                        Padding(
                            padding: const EdgeInsets.all(12),
                            child: Text('给你的小建议：${insight!['advice']}')),
                        Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 12),
                            child:
                                Text('观察记录：${insight!['objective_timeline']}'))
                      ]))),
        const SectionLabel('过去的成长'),
        const AppCard(
            child: ListTile(
                leading: Icon(Icons.history),
                title: Text('历史总结与反馈'),
                subtitle: Text('过去的成长信息始终可以查看'))),
      ]);

  Widget _profile(BuildContext context) {
    final guardians =
        (profile?['guardians'] as List? ?? const []).cast<dynamic>();
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('我的',
          style: Theme.of(context)
              .textTheme
              .headlineSmall
              ?.copyWith(fontWeight: FontWeight.w700)),
      const SizedBox(height: 18),
      const SectionLabel('关联的监护人'),
      AppCard(
          child: guardians.isEmpty
              ? const ListTile(
                  leading: Icon(Icons.group_outlined),
                  title: Text('暂未读取到关联监护人'))
              : Column(children: [
                  for (final guardian in guardians)
                    ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const CircleAvatar(child: Icon(Icons.person)),
                        title: Text(guardian['name'] as String),
                        subtitle: const Text('关联监护人'))
                ])),
      const SizedBox(height: 24),
      OutlinedButton.icon(
          onPressed: _confirmLogout,
          icon: const Icon(Icons.logout),
          label: const Text('退出此设备绑定')),
      const Padding(
          padding: EdgeInsets.only(top: 8),
          child: Text('退出只会移除这台设备的登录凭据，不会删除学习记录或家庭关联。',
              style: TextStyle(fontSize: 12, color: Colors.blueGrey))),
    ]);
  }

  Future<void> _load() async {
    tasks = await ref.read(apiProvider).assignments(widget.wardId);
    try {
      profile = await ref.read(apiProvider).wardProfile();
    } catch (_) {}
    try {
      plan = await ref.read(apiProvider).plan(widget.wardId, DateTime.now());
    } on DioException catch (error) {
      if (error.response?.statusCode != 404) rethrow;
      plan = null;
    }
    _restoreActiveSession();
    if (mounted) setState(() {});
  }

  Future<void> _confirmLogout() async {
    final approved = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
                title: const Text('退出此设备绑定？'),
                content: const Text('之后需要用新的绑定码才能再次进入学习空间。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(dialogContext, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(dialogContext, true),
                      child: const Text('确认退出'))
                ]));
    if (approved != true || !mounted) return;
    await ref.read(authProvider.notifier).logout();
    if (mounted) context.go('/login');
  }

  void _restoreActiveSession() {
    if (session != null) {
      return;
    }
    final candidates = <Map<String, dynamic>>[
      ...((plan?['items'] as List? ?? const []).cast<Map<String, dynamic>>()),
      ...tasks.cast<Map<String, dynamic>>(),
    ];
    final current = candidates.cast<Map<String, dynamic>?>().firstWhere(
        (item) =>
            item?['session'] != null && item?['session']['status'] == 'active',
        orElse: () => null);
    if (current == null) {
      return;
    }
    final data = current['session'] as Map<String, dynamic>;
    session = data['id'] as String;
    savedSeconds = data['active_seconds'] as int? ?? 0;
    watch
      ..reset()
      ..start();
    timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  int get _elapsedSeconds => savedSeconds + watch.elapsed.inSeconds;

  Future<void> _finish() async {
    watch.stop();
    await ref.read(apiProvider).finishSession(session!, _elapsedSeconds);
    timer?.cancel();
    session = null;
    savedSeconds = 0;
    await _load();
  }

  Future<void> _review() async {
    try {
      await ref.read(apiProvider).review(widget.wardId, DateTime.now(), '顺利');
      insight =
          await ref.read(apiProvider).insight(widget.wardId, DateTime.now());
      if (mounted) setState(() => tab = 2);
    } catch (e) {
      if (mounted) showMessage(context, '提交自我总结失败：$e');
    }
  }

  Future<void> _taskTapped(Map<String, dynamic> item, bool planned) async {
    final status = item['status'] as String? ?? 'pending';
    final data = item['session'] as Map<String, dynamic>?;
    if (status == 'completed') {
      return;
    }
    if (status == 'active' && data != null) {
      return _showActiveActions(data['id'] as String);
    }
    if (status == 'paused' && data != null) {
      return _confirm(
        title: '继续学习？',
        message: '会继续累计这项任务的学习时长。',
        confirm: '确认继续',
        action: () async {
          await ref.read(apiProvider).resumeSession(data['id'] as String);
          await _load();
        },
      );
    }
    await _confirm(
      title: '开始学习？',
      message: '开始后你可以随时暂停或完成。',
      confirm: '确认开始',
      action: () async {
        final result = planned
            ? await ref.read(apiProvider).startSession(item['id'] as String)
            : await ref
                .read(apiProvider)
                .startAssignmentSession(item['id'] as String);
        session = result['id'] as String;
        savedSeconds = result['active_seconds'] as int? ?? 0;
        watch
          ..reset()
          ..start();
        timer?.cancel();
        timer = Timer.periodic(const Duration(seconds: 1), (_) {
          if (mounted) setState(() {});
        });
        await _load();
      },
    );
  }

  Future<void> _showActiveActions(String sessionId) =>
      showModalBottomSheet<void>(
        context: context,
        builder: (sheetContext) => Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('这项任务正在进行',
                      style:
                          TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 8),
                  Text('已累计 ${_elapsedSeconds ~/ 60} 分钟。你可以按自己的节奏决定下一步。'),
                  const SizedBox(height: 16),
                  FilledButton(
                      onPressed: () {
                        Navigator.pop(sheetContext);
                        _confirm(
                            title: '完成这项任务？',
                            message: '完成后会记录本次学习时长。',
                            confirm: '确认完成',
                            action: _finish);
                      },
                      child: const Text('完成任务')),
                  const SizedBox(height: 8),
                  OutlinedButton(
                      onPressed: () {
                        Navigator.pop(sheetContext);
                        _confirm(
                            title: '暂停这项任务？',
                            message: '学习时长会保留，之后可以继续。',
                            confirm: '确认暂停',
                            action: () async {
                              watch.stop();
                              await ref
                                  .read(apiProvider)
                                  .pauseSession(sessionId, _elapsedSeconds);
                              timer?.cancel();
                              session = null;
                              savedSeconds = 0;
                              await _load();
                            });
                      },
                      child: const Text('暂停')),
                ])),
      );

  Future<void> _confirm(
      {required String title,
      required String message,
      required String confirm,
      required Future<void> Function() action}) async {
    final approved = await showDialog<bool>(
        context: context,
        builder: (dialogContext) =>
            AlertDialog(title: Text(title), content: Text(message), actions: [
              TextButton(
                  onPressed: () => Navigator.pop(dialogContext, false),
                  child: const Text('取消')),
              FilledButton(
                  onPressed: () => Navigator.pop(dialogContext, true),
                  child: Text(confirm))
            ]));
    if (approved != true) return;
    try {
      await action();
    } catch (error) {
      if (mounted) showMessage(context, '操作没有完成，请稍后再试：$error');
    }
  }

  Future<void> _pickPlanImage() async {
    _openPlanChat();
    final image = await ImagePicker()
        .pickImage(source: ImageSource.gallery, imageQuality: 85);
    if (image == null || !mounted) return;
    final extension = image.name.split('.').last.toLowerCase();
    if (!const {'jpg', 'jpeg', 'png', 'webp'}.contains(extension)) {
      showMessage(context, '暂只支持 JPG、PNG 或 WebP 图片');
      return;
    }
    try {
      final key = await ref
          .read(apiProvider)
          .uploadCompanionAttachment(await image.readAsBytes(), extension);
      if (mounted) {
        setState(() => planAttachments.add(key));
        await _submitPlanInput('请根据这张图片帮我安排今天的学习。');
      }
    } catch (_) {
      if (mounted) showMessage(context, '图片上传失败，请重试');
    }
  }

  Future<void> _submitPlanInput(String text) async {
    if (planSending) return;
    setState(() => planSending = true);
    try {
      final result = await ref.read(apiProvider).companionTurn(
          content: text,
          threadId: companionThreadId,
          expectedThreadVersion: companionThreadVersion,
          attachmentKeys: planAttachments);
      if (!mounted) return;
      final interaction =
          Map<String, dynamic>.from(result['interaction'] as Map? ?? const {});
      companionThreadId = result['thread_id'] as String?;
      companionThreadVersion = result['thread_version'] as int?;
      if (companionThreadId != null && companionThreadVersion != null) {
        await ref
            .read(tokenStorageProvider)
            .saveCompanionThread(companionThreadId!, companionThreadVersion!);
      }
      setState(() {
        failedPlanText = null;
        planFeedback = interaction['model_guidance'] as String?;
        planDraft = (interaction['items'] as List? ?? const [])
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
      });
      await _refreshTranscript();
    } catch (_) {
      if (mounted) {
        setState(() => failedPlanText = text);
        showMessage(context, '暂时无法整理今天的计划，请重试');
      }
    } finally {
      if (mounted) setState(() => planSending = false);
    }
  }

  Future<void> _confirmPlanDraft() async {
    if (planDraft.isEmpty || planSending) return;
    setState(() => planSending = true);
    try {
      final result = await ref.read(apiProvider).companionTurn(
          content: '确认这个计划',
          threadId: companionThreadId,
          expectedThreadVersion: companionThreadVersion,
          planningConfirm: true);
      companionThreadVersion = result['thread_version'] as int?;
      if (companionThreadId != null && companionThreadVersion != null) {
        await ref
            .read(tokenStorageProvider)
            .saveCompanionThread(companionThreadId!, companionThreadVersion!);
      }
      planAttachments.clear();
      planDraft = [];
      planFeedback = null;
      await _load();
      await _refreshTranscript();
      if (mounted) showMessage(context, '今天计划已确认');
    } catch (_) {
      if (mounted) showMessage(context, '确认计划失败，请稍后重试');
    } finally {
      if (mounted) setState(() => planSending = false);
    }
  }

  Future<void> _refreshTranscript() async {
    if (companionThreadId == null) return;
    final messages =
        await ref.read(apiProvider).companionMessages(companionThreadId!);
    if (!mounted) return;
    setState(() {
      planMessages
        ..clear()
        ..addAll(messages.map((message) {
          final item = Map<String, dynamic>.from(message as Map);
          return {
            'label': item['author_type'] == 'ward' ? '我' : '读学 AI',
            'content': item['content'] as String,
          };
        }));
    });
  }

  Future<void> _restoreCompanionThread() async {
    final tokens = ref.read(tokenStorageProvider);
    final threadId = await tokens.companionThreadId;
    final version = await tokens.companionThreadVersion;
    if (threadId == null || version == null || !mounted) return;
    companionThreadId = threadId;
    companionThreadVersion = version;
    try {
      await _refreshTranscript();
    } catch (_) {
      // A deleted/expired Thread is non-fatal; the next Ward turn starts fresh.
      if (mounted) {
        companionThreadId = null;
        companionThreadVersion = null;
      }
    }
  }

  String _weekday(DateTime day) =>
      const ['一', '二', '三', '四', '五', '六', '日'][day.weekday - 1];
}

class _HomeEmptyCard extends StatelessWidget {
  const _HomeEmptyCard({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) => Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
          color: Colors.white,
          border: Border.all(color: const Color(0xffe2e8f0)),
          borderRadius: BorderRadius.circular(16)),
      child: Text(message, style: const TextStyle(color: Colors.blueGrey)));
}

class _HomeOverlay extends StatelessWidget {
  const _HomeOverlay({
    required this.title,
    required this.subtitle,
    required this.onClose,
    required this.child,
  });
  final String title;
  final String subtitle;
  final VoidCallback onClose;
  final Widget child;

  @override
  Widget build(BuildContext context) => Positioned.fill(
      child: ColoredBox(
          color: const Color(0x660c1222),
          child: SafeArea(
              child: Padding(
                  padding: const EdgeInsets.fromLTRB(10, 10, 10, 82),
                  child: Material(
                      borderRadius: BorderRadius.circular(24),
                      clipBehavior: Clip.antiAlias,
                      child: Column(children: [
                        Padding(
                            padding: const EdgeInsets.fromLTRB(16, 16, 8, 12),
                            child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  const CircleAvatar(
                                      backgroundColor: Color(0xff0f766e),
                                      foregroundColor: Colors.white,
                                      child: Icon(Icons.auto_awesome)),
                                  const SizedBox(width: 12),
                                  Expanded(
                                      child: Column(
                                          crossAxisAlignment:
                                              CrossAxisAlignment.start,
                                          children: [
                                        Text(title,
                                            style: const TextStyle(
                                                fontWeight: FontWeight.w700,
                                                fontSize: 16)),
                                        Text(subtitle,
                                            style: const TextStyle(
                                                fontSize: 12,
                                                color: Colors.blueGrey)),
                                      ])),
                                  IconButton(
                                      onPressed: onClose,
                                      tooltip: '关闭',
                                      icon: const Icon(Icons.close)),
                                ])),
                        const Divider(height: 1),
                        Expanded(
                            child: SingleChildScrollView(
                                padding: const EdgeInsets.all(16),
                                child: child)),
                      ]))))));
}

class _ChatBubble extends StatelessWidget {
  const _ChatBubble({required this.label, required this.text});
  final String label;
  final String text;

  @override
  Widget build(BuildContext context) {
    final isWard = label == '我';
    return Align(
        alignment: isWard ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
            constraints: const BoxConstraints(maxWidth: 300),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
                color:
                    isWard ? const Color(0xffdbeafe) : const Color(0xfff8fafc),
                border: Border.all(
                    color: isWard
                        ? const Color(0xff93c5fd)
                        : const Color(0xffe2e8f0)),
                borderRadius: BorderRadius.circular(16)),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label,
                  style: const TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: Colors.blueGrey)),
              const SizedBox(height: 4),
              Text(text),
            ])));
  }
}
