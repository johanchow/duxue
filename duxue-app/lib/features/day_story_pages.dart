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
  String? session, answer;
  int tab = 0;
  final watch = Stopwatch();
  final planAttachments = <String>[];
  List<Map<String, dynamic>> planDraft = [];
  String? planFeedback;
  bool planSending = false;
  Timer? timer;
  int savedSeconds = 0;
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    timer?.cancel();
    if (planAttachments.isNotEmpty) {
      unawaited(ref
          .read(apiProvider)
          .cleanupPlanIntake(widget.wardId, planAttachments));
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
          child: switch (tab) {
        0 => _home(context),
        1 => _ai(context),
        2 => _growth(context),
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
                icon: Icon(Icons.chat_bubble_outline),
                selectedIcon: Icon(Icons.chat_bubble),
                label: 'AI 伙伴'),
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
        .where((item) => !plannedAssignmentIds.contains(item['id']))
        .toList();
    return Stack(children: [
      ListView(padding: const EdgeInsets.fromLTRB(16, 14, 16, 156), children: [
        Text(
            '周${_weekday(DateTime.now())} · ${DateTime.now().month} 月 ${DateTime.now().day} 日',
            style: const TextStyle(fontSize: 12, color: Colors.blueGrey)),
        const SizedBox(height: 4),
        Text('开始按自己的节奏学习吧',
            style: Theme.of(context)
                .textTheme
                .headlineSmall
                ?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 20),
        _sectionHead(
            '今日计划', plan?['status'] == 'confirmed' ? '已确认 · 你说了算' : '还没确认'),
        AppCard(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
            child: planned.isEmpty
                ? const Padding(
                    padding: EdgeInsets.all(16),
                    child: Text('今天还没有确认计划。可以在下方告诉我怎么安排。'))
                : Column(children: [
                    for (var i = 0; i < planned.length; i++)
                      _timelineTask(planned[i] as Map<String, dynamic>, i == 0),
                  ])),
        const SizedBox(height: 18),
        _sectionHead('未进入今天计划', '${pool.length} 项'),
        AppCard(
            padding: EdgeInsets.zero,
            child: pool.isEmpty
                ? const Padding(
                    padding: EdgeInsets.all(18),
                    child: Center(child: Text('任务池已经空了。')))
                : Column(children: [
                    for (final item in pool)
                      _poolTask(item as Map<String, dynamic>)
                  ])),
        const Padding(
            padding: EdgeInsets.only(top: 8, left: 2, right: 2),
            child: Text('这些不会自动排进今天。想加进来、延后或拆开，可以告诉 AI 伙伴。',
                style: TextStyle(fontSize: 12, color: Colors.blueGrey))),
        if (planned.isNotEmpty) ...[
          const SizedBox(height: 18),
          FilledButton.tonal(
              onPressed: _review, child: const Text('完成今日计划，先说说自己的感受')),
        ],
      ]),
      Positioned(left: 16, right: 16, bottom: 12, child: _chatEntry()),
    ]);
  }

  Widget _sectionHead(String title, String meta) => Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(title.toUpperCase(),
            style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: Colors.blueGrey,
                letterSpacing: 1)),
        Text(meta,
            style: const TextStyle(fontSize: 12, color: Colors.blueGrey)),
      ]));

  Widget _timelineTask(Map<String, dynamic> item, bool first) {
    final status = item['status'] as String? ?? 'pending';
    final sessionData = item['session'] as Map<String, dynamic>?;
    final label = status == 'active'
        ? '进行中'
        : status == 'paused'
            ? '已暂停'
            : status == 'completed'
                ? '已完成'
                : first
                    ? '当前'
                    : '待开始';
    return InkWell(
        onTap: () => _taskTapped(item, true),
        child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(
                  width: 48,
                  child: Text(first ? '19:00' : '稍后',
                      style: const TextStyle(
                          fontSize: 12, color: Colors.blueGrey))),
              Container(
                  width: 10,
                  height: 10,
                  margin: const EdgeInsets.only(top: 4, right: 12),
                  decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color:
                          status == 'completed' ? Colors.blueGrey : brandBlue)),
              Expanded(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    Text(item['title'] as String,
                        style: TextStyle(
                            fontWeight: FontWeight.w700,
                            decoration: status == 'completed'
                                ? TextDecoration.lineThrough
                                : null)),
                    Text('约 ${item['planned_minutes'] ?? 30} 分钟',
                        style: const TextStyle(
                            fontSize: 12, color: Colors.blueGrey)),
                    const SizedBox(height: 5),
                    StatusPill(
                        text: label,
                        color: status == 'completed'
                            ? Colors.blueGrey
                            : status == 'paused'
                                ? Colors.orange
                                : brandBlue),
                    if (sessionData != null) const SizedBox(height: 1),
                  ])),
            ])));
  }

  Widget _poolTask(Map<String, dynamic> item) {
    final status = item['status'] as String? ?? 'open';
    return InkWell(
        onTap: () => _taskTapped(item, false),
        child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
            child: Row(children: [
              const Icon(Icons.check_box_outline_blank,
                  color: Color(0xff94a3b8)),
              const SizedBox(width: 12),
              Expanded(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                    Text(item['title'] as String,
                        style: const TextStyle(fontWeight: FontWeight.w700)),
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
            ])));
  }

  Widget _chatEntry() => AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        VoiceComposer(
          baseUrl: apiBaseUrl,
          tokens: ref.read(tokenStorageProvider),
          telemetry: ref.read(telemetryProvider),
            holdToTalkText: '说今天怎么安排',
            helperText: '加任务 · 改顺序 · 调时长 · 补遗漏',
            enabled: !planSending,
            onPickImage: _pickPlanImage,
            onVoiceFinal: _submitPlanInput),
        if (planAttachments.isNotEmpty)
          Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('已添加 ${planAttachments.length} 张图片，发送后我会一起整理。',
                  style:
                      const TextStyle(fontSize: 12, color: Colors.blueGrey))),
        if (planFeedback != null)
          Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(planFeedback!)),
        if (planDraft.isNotEmpty) ...[
          const SizedBox(height: 8),
          const Text('今天计划草稿', style: TextStyle(fontWeight: FontWeight.w700)),
          for (final item in planDraft)
            Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                    '• ${item['title']} · 约 ${item['planned_minutes']} 分钟')),
          const SizedBox(height: 8),
          FilledButton(
              onPressed: planSending ? null : _confirmPlanIntake,
              child: const Text('确认今天计划')),
        ],
      ]));

  Widget _ai(BuildContext context) =>
      ListView(padding: const EdgeInsets.all(16), children: [
        const Text('学习卡壳时随时问，我会一步步陪你想明白。',
            style: TextStyle(color: Colors.blueGrey)),
        const SizedBox(height: 14),
        if (session == null)
          const AppCard(
              child: Padding(
                  padding: EdgeInsets.all(20),
                  child: Text('先从首页开始一个计划任务，再来和 AI 伙伴一起解决问题。')))
        else
          _Companion(
              seconds: _elapsedSeconds,
              answer: answer,
              onAsk: _ask,
              onFinish: _finish)
      ]);

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

  Future<void> _ask(String text) async {
    answer = await ref.read(apiProvider).ask(session!, text);
    if (mounted) setState(() {});
  }

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
    final image = await ImagePicker()
        .pickImage(source: ImageSource.gallery, imageQuality: 85);
    if (image == null || !mounted) return;
    final extension = image.name.split('.').last.toLowerCase();
    if (!const {'jpg', 'jpeg', 'png', 'webp'}.contains(extension)) {
      showMessage(context, '暂只支持 JPG、PNG 或 WebP 图片');
      return;
    }
    try {
      final key = await ref.read(apiProvider).uploadPlanIntakeImage(
          widget.wardId, await image.readAsBytes(), extension);
      if (mounted) {
        setState(() => planAttachments.add(key));
        await _submitPlanInput('');
      }
    } catch (_) {
      if (mounted) showMessage(context, '图片上传失败，请重试');
    }
  }

  Future<void> _submitPlanInput(String text) async {
    if (planSending) return;
    setState(() => planSending = true);
    try {
      final result = await ref.read(apiProvider).respondToPlanIntake(
          widget.wardId, DateTime.now(),
          content: text,
          draftItems: planDraft,
          attachmentKeys: planAttachments);
      if (!mounted) return;
      setState(() {
        planFeedback = result['assistant_text'] as String?;
        planDraft = (result['items'] as List? ?? const [])
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList();
      });
    } catch (_) {
      if (mounted) showMessage(context, '暂时无法整理今天的计划，请重试');
    } finally {
      if (mounted) setState(() => planSending = false);
    }
  }

  Future<void> _confirmPlanIntake() async {
    if (planDraft.isEmpty || planSending) return;
    setState(() => planSending = true);
    try {
      await ref.read(apiProvider).confirmPlanIntake(
          widget.wardId, DateTime.now(), planDraft, planAttachments);
      planAttachments.clear();
      planDraft = [];
      planFeedback = null;
      await _load();
      if (mounted) showMessage(context, '今天计划已确认');
    } catch (_) {
      if (mounted) showMessage(context, '确认计划失败，请稍后重试');
    } finally {
      if (mounted) setState(() => planSending = false);
    }
  }

  String _weekday(DateTime day) =>
      const ['一', '二', '三', '四', '五', '六', '日'][day.weekday - 1];
}

class _Companion extends StatefulWidget {
  const _Companion(
      {required this.seconds,
      required this.answer,
      required this.onAsk,
      required this.onFinish});
  final int seconds;
  final String? answer;
  final Future<void> Function(String) onAsk;
  final VoidCallback onFinish;
  @override
  State<_Companion> createState() => _CompanionState();
}

class _CompanionState extends State<_Companion> {
  final input = TextEditingController();
  @override
  Widget build(BuildContext context) => Card(
      child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(children: [
            Text('专注 ${widget.seconds ~/ 60} 分钟'),
            TextField(
                controller: input,
                decoration: const InputDecoration(labelText: '卡住了？问问 AI 伙伴'),
                onSubmitted: widget.onAsk),
            if (widget.answer != null) Text(widget.answer!),
            TextButton(onPressed: widget.onFinish, child: const Text('完成任务'))
          ])));
}
