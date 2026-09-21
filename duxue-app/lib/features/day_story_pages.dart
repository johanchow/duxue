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
  String? planInteractionKind;
  Map<String, dynamic>? planConfirmAction;
  String? planDraftId;
  int? planDraftVersion;
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
        _contextHeader('未排期任务', meta: '${pool.length} 项 · 左滑删除'),
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
              style: const TextStyle(
                  fontSize: 12,
                  color: Color(0xff8b95a8),
                  letterSpacing: 0.2)),
          const SizedBox(height: 4),
          Text('晚上好，${profile?['display_name'] ?? '同学'}',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: const Color(0xff0c1222))),
          const SizedBox(height: 5),
          const Text('你先说，我来帮你记录和检查安排。',
              style: TextStyle(fontSize: 13, color: Color(0xff5b667a))),
        ])),
      ]));

  Widget _contextHeader(String title,
          {String? meta, VoidCallback? action, String? actionLabel}) =>
      Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Row(children: [
            Container(
              width: 6,
              height: 6,
              decoration: const BoxDecoration(
                color: Color(0xff0f766e),
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: Color(0xffe6f4f1),
                    spreadRadius: 3,
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Text(title.toUpperCase(),
                style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: Color(0xff8b95a8),
                    letterSpacing: 0.8)),
            const Spacer(),
            if (meta != null)
              Text(meta,
                  style: const TextStyle(
                      fontSize: 12, color: Color(0xff8b95a8))),
            if (action != null)
              TextButton(
                  onPressed: action,
                  style: TextButton.styleFrom(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                    minimumSize: Size.zero,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: Text(actionLabel ?? '查看',
                      style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: Color(0xff0f766e)))),
          ]));

  Widget _planRail(List<dynamic> planned) => SizedBox(
      height: 128,
      child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: planned.length,
          separatorBuilder: (_, __) => const SizedBox(width: 8),
          itemBuilder: (_, index) {
            final item = planned[index] as Map<String, dynamic>;
            final isCurrent = _isItemCurrent(item, index);
            final startTime = _formatItemStartTime(item, index, planned);
            final durationText = _formatPlannedDuration(item);
            final title = item['title'] as String? ?? '计划项';

            return SizedBox(
                width: 148,
                child: Material(
                    color: Colors.transparent,
                    child: InkWell(
                        borderRadius: BorderRadius.circular(16),
                        onTap: () => _openPlanChat(title),
                        child: Ink(
                            decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(16),
                                gradient: isCurrent
                                    ? const LinearGradient(
                                        begin: Alignment.topLeft,
                                        end: Alignment.bottomRight,
                                        colors: [
                                            Color(0xf2ccfbf1),
                                            Color(0xe6ffffff),
                                          ])
                                    : null,
                                color: isCurrent ? null : Colors.white,
                                border: Border.all(
                                    color: isCurrent
                                        ? const Color(0x590d9488)
                                        : const Color(0x1a0f172a)),
                                boxShadow: const [
                                  BoxShadow(
                                      color: Color(0x0c0c1222),
                                      blurRadius: 10,
                                      offset: Offset(0, 4)),
                                ]),
                            padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
                            child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(startTime,
                                      style: TextStyle(
                                          fontSize: 11,
                                          fontFeatures: const [
                                            FontFeature.tabularFigures()
                                          ],
                                          fontWeight: FontWeight.w600,
                                          color: isCurrent
                                              ? const Color(0xff0f766e)
                                              : const Color(0xff8b95a8))),
                                  const SizedBox(height: 4),
                                  Text(title,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                          fontSize: 13,
                                          height: 1.25,
                                          fontWeight: FontWeight.w700,
                                          color: Color(0xff0c1222))),
                                  const SizedBox(height: 4),
                                  Text(durationText,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                          fontSize: 11,
                                          color: Color(0xff5b667a))),
                                  const Spacer(),
                                  if (isCurrent)
                                    Container(
                                        padding: const EdgeInsets.symmetric(
                                            horizontal: 7, vertical: 2),
                                        decoration: BoxDecoration(
                                            color: const Color(0xffe6f4f1),
                                            borderRadius:
                                                BorderRadius.circular(999)),
                                        child: const Text('当前',
                                            style: TextStyle(
                                                fontSize: 10,
                                                fontWeight: FontWeight.w700,
                                                color: Color(0xff0f766e)))),
                                ]))))) ;
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
            onDismissed: (_) => _removePoolTask(item),
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

  Widget _planListOverlay(List<dynamic> planned) => _PlanSheetOverlay(
      title: '今日计划',
      subtitle: '已确认 · 共 ${planned.length} 项 · 你说了算',
      onClose: () => setState(() => planListOpen = false),
      child: planned.isEmpty
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text('还没有确认计划。',
                    style: TextStyle(color: Color(0xff5b667a))),
              ),
            )
          : ListView.builder(
              padding: const EdgeInsets.symmetric(vertical: 14),
              itemCount: planned.length,
              itemBuilder: (_, index) {
                final item = planned[index] as Map<String, dynamic>;
                final isCurrent = _isItemCurrent(item, index);
                final time = _formatItemStartTime(item, index, planned);
                final subtitle = _formatPlanItemSubtitle(item);
                final title = item['title'] as String? ?? '计划项';

                return _TimelineRow(
                    time: time,
                    title: title,
                    subtitle: subtitle,
                    isCurrent: isCurrent,
                    isFirst: index == 0,
                    isLast: index == planned.length - 1,
                    onTap: () => setState(() {
                          planListOpen = false;
                          chatSubject = title;
                          planChatOpen = true;
                        }));
              }));

  bool _isItemCurrent(Map<String, dynamic> item, int index) {
    final status = item['status'] as String?;
    if (status == 'active' || status == 'in_progress') {
      return true;
    }
    return index == 0;
  }

  String _formatPlannedDuration(Map<String, dynamic> item) {
    final details = (item['details'] as String?) ?? '';
    if (details.contains('固定') || details.contains('不可移动')) {
      return '固定 · 不可移动';
    }
    final mins = item['planned_minutes'] as num?;
    if (mins != null && mins > 0) {
      return '约 ${mins.toInt()} 分钟';
    }
    return '约 30 分钟';
  }

  String _formatPlanItemSubtitle(Map<String, dynamic> item) {
    final details = item['details'] as String?;
    final duration = _formatPlannedDuration(item);
    if (details != null && details.trim().isNotEmpty) {
      if (details.contains('固定') || details.contains('不可移动')) {
        return '固定时间 · 不可移动';
      }
      return '$details · $duration';
    }
    return duration;
  }

  String _formatItemStartTime(
      Map<String, dynamic> item, int index, List<dynamic> planned) {
    final startAt = item['start_at'] ?? item['start_time'];
    if (startAt is String && startAt.trim().isNotEmpty) {
      final parsed = _extractClockTime(startAt);
      if (parsed != null) return parsed;
    }

    var baseHour = 19;
    var baseMinute = 0;

    for (int i = 0; i < planned.length; i++) {
      final s = (planned[i] as Map<String, dynamic>)['start_at'];
      if (s is String && s.trim().isNotEmpty) {
        final clock = _extractClockTime(s);
        if (clock != null) {
          final parts = clock.split(':');
          if (parts.length == 2) {
            final h = int.tryParse(parts[0]);
            final m = int.tryParse(parts[1]);
            if (h != null && m != null) {
              int totalMinsBefore = 0;
              for (int k = 0; k < i; k++) {
                final mins = (planned[k] as Map<String, dynamic>)['planned_minutes']
                        as num? ??
                    30;
                totalMinsBefore += mins.toInt();
              }
              final startMins = (h * 60 + m) - totalMinsBefore;
              baseHour = (startMins ~/ 60) % 24;
              baseMinute = startMins % 60;
              if (baseMinute < 0) {
                baseMinute += 60;
                baseHour = (baseHour - 1 + 24) % 24;
              }
              break;
            }
          }
        }
      }
    }

    int accumulatedMinutes = 0;
    for (int i = 0; i < index; i++) {
      final mins = (planned[i] as Map<String, dynamic>)['planned_minutes']
              as num? ??
          30;
      accumulatedMinutes += mins.toInt();
    }

    final itemTotalMinutes =
        (baseHour * 60 + baseMinute + accumulatedMinutes) % (24 * 60);
    final h = (itemTotalMinutes ~/ 60).toString().padLeft(2, '0');
    final m = (itemTotalMinutes % 60).toString().padLeft(2, '0');
    return '$h:$m';
  }

  static String? _extractClockTime(String raw) {
    final match = RegExp(r'(?:^|[T\s])(\d{1,2}):(\d{2})').firstMatch(raw);
    if (match != null) {
      final hour = match.group(1)!.padLeft(2, '0');
      final minute = match.group(2)!.padLeft(2, '0');
      return '$hour:$minute';
    }
    final dt = DateTime.tryParse(raw);
    if (dt != null) {
      final hour = dt.hour.toString().padLeft(2, '0');
      final minute = dt.minute.toString().padLeft(2, '0');
      return '$hour:$minute';
    }
    return null;
  }

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
        if (planInteractionKind == 'plan_confirm_list' &&
            planConfirmAction != null &&
            planDraft.isNotEmpty) ...[
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
                      child: Text('• ${item['title']} · '
                          '${_draftSlotLabel(item)} · '
                          '约 ${item['planned_minutes']} 分钟')),
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
                          onPressed: planSending || planConfirmAction == null
                              ? null
                              : _confirmPlanDraft,
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

  String _draftSlotLabel(Map<String, dynamic> item) {
    final start = DateTime.tryParse(item['start_at'] as String? ?? '');
    final end = DateTime.tryParse(item['end_at'] as String? ?? '');
    String clock(DateTime value) =>
        '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
    if (start == null) return '未排时间';
    return end == null ? '${clock(start)} 开始' : '${clock(start)}–${clock(end)}';
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

  Future<void> _removePoolTask(Map<String, dynamic> item) async {
    final id = item['id'] as String;
    setState(() => removedPoolTaskIds.add(id));
    try {
      await ref.read(apiProvider).deleteAssignment(widget.wardId, id);
      if (!mounted) return;
      setState(() => tasks.removeWhere((row) => row['id'] == id));
      showMessage(context, '「${item['title']}」已从任务池移除');
    } on DioException catch (error) {
      if (!mounted) return;
      setState(() => removedPoolTaskIds.remove(id));
      final detail = error.response?.data;
      final message = detail is Map && detail['detail'] is String
          ? detail['detail'] as String
          : '删除失败，请稍后重试';
      showMessage(context, message);
      await _load();
    }
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
      final objectRef = Map<String, dynamic>.from(
          interaction['object_ref'] as Map? ?? const {});
      final actions = (interaction['actions'] as List? ?? const [])
          .map((action) => Map<String, dynamic>.from(action as Map));
      Map<String, dynamic>? draft;
      if (objectRef['context'] == 'planning' &&
          objectRef['object_id'] is String) {
        draft = await ref
            .read(apiProvider)
            .companionPlanDraft(objectRef['object_id'] as String);
      }
      setState(() {
        failedPlanText = null;
        planFeedback = ((interaction['parts'] as List? ?? const []).isNotEmpty)
            ? Map<String, dynamic>.from(
                (interaction['parts'] as List).first as Map)['text'] as String?
            : null;
        planConfirmAction = null;
        for (final action in actions) {
          if (action['command'] == 'confirm_plan' &&
              action['enabled'] == true) {
            planConfirmAction = action;
            break;
          }
        }
        planInteractionKind = interaction['kind'] as String?;
        final canReview = planInteractionKind == 'plan_confirm_list' &&
            planConfirmAction != null;
        planDraft = canReview
            ? (draft?['items'] as List? ?? const [])
                .map((item) => Map<String, dynamic>.from(item as Map))
                .toList()
            : [];
        planDraftId = canReview ? (draft?['draft_id'] as String?) : null;
        planDraftVersion =
            canReview ? (draft?['object_version'] as int?) : null;
      });
      // RegisterTask happens inside the Planning workflow.  Reload the home
      // projections immediately so an unscheduled task is visible in its
      // actual task-pool home, not only in this transient chat card.
      await _load();
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
    if (planDraft.isEmpty ||
        planSending ||
        planConfirmAction == null ||
        planDraftId == null ||
        planDraftVersion == null) {
      return;
    }
    setState(() => planSending = true);
    try {
      final result = await ref.read(apiProvider).companionTurn(
          content: '确认这个计划',
          threadId: companionThreadId,
          expectedThreadVersion: companionThreadVersion,
          structuredCommand: {
            'interaction_id': planConfirmAction!['id'],
            'command': 'confirm_plan',
            'payload': {
              'draft_id': planDraftId,
              'expected_draft_version': planDraftVersion,
            },
          });
      final interaction =
          Map<String, dynamic>.from(result['interaction'] as Map? ?? const {});
      final confirmed = result['run_status'] == 'closed' &&
          interaction['status'] == 'confirmed';
      if (!confirmed) {
        throw StateError('服务端尚未确认计划');
      }
      companionThreadVersion = result['thread_version'] as int?;
      if (companionThreadId != null && companionThreadVersion != null) {
        await ref
            .read(tokenStorageProvider)
            .saveCompanionThread(companionThreadId!, companionThreadVersion!);
      }
      planAttachments.clear();
      planDraft = [];
      planFeedback = null;
      planInteractionKind = null;
      planConfirmAction = null;
      planDraftId = null;
      planDraftVersion = null;
      await _load();
      await _refreshTranscript();
      if (mounted) showMessage(context, '今天计划已确认');
    } on DioException catch (error) {
      if (error.response?.statusCode == 409) {
        final body = error.response?.data;
        final detail = body is Map ? body['detail'] as String? : null;
        if (mounted) {
          setState(() {
            planDraft = [];
            planConfirmAction = null;
            planDraftId = null;
            planDraftVersion = null;
            planInteractionKind = null;
          });
        }
        // The rejected action is no longer usable. Refresh projections and
        // the thread version best-effort; neither failure should suppress the
        // recovery message or leave the stale card on screen.
        try {
          await _load();
          await _refreshTranscript();
        } catch (_) {}
        if (mounted) {
          showMessage(context, detail ?? '计划已变化，已刷新，请重新说明或确认。');
        }
      } else if (mounted) {
        showMessage(context, '确认计划失败，请稍后重试');
      }
    } catch (_) {
      if (mounted) showMessage(context, '确认计划失败，请稍后重试');
    } finally {
      if (mounted) setState(() => planSending = false);
    }
  }

  Future<void> _refreshTranscript() async {
    if (companionThreadId == null) return;
    final transcript =
        await ref.read(apiProvider).companionMessages(companionThreadId!);
    final version = transcript['thread_version'] as int?;
    final messages = transcript['messages'] as List? ?? const [];
    if (!mounted) return;
    setState(() {
      companionThreadVersion = version;
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
    if (version != null && companionThreadId != null) {
      await ref
          .read(tokenStorageProvider)
          .saveCompanionThread(companionThreadId!, version);
    }
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

class _PlanSheetOverlay extends StatelessWidget {
  const _PlanSheetOverlay({
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
                color: Colors.white,
                borderRadius: BorderRadius.circular(24),
                clipBehavior: Clip.antiAlias,
                elevation: 10,
                shadowColor: const Color(0x2e0c1222),
                child: Column(
                  children: [
                    Container(
                      padding: const EdgeInsets.fromLTRB(16, 16, 12, 12),
                      decoration: const BoxDecoration(
                        border: Border(
                          bottom: BorderSide(color: Color(0x1a0f172a)),
                        ),
                      ),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  title,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w700,
                                    fontSize: 16,
                                    color: Color(0xff0c1222),
                                    letterSpacing: -0.3,
                                  ),
                                ),
                                const SizedBox(height: 3),
                                Text(
                                  subtitle,
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: Color(0xff5b667a),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          Container(
                            width: 32,
                            height: 32,
                            decoration: BoxDecoration(
                              color: const Color(0xfff8fafc),
                              border:
                                  Border.all(color: const Color(0x1a0f172a)),
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: IconButton(
                              padding: EdgeInsets.zero,
                              iconSize: 16,
                              onPressed: onClose,
                              tooltip: '关闭',
                              icon: const Icon(Icons.close,
                                  color: Color(0xff5b667a)),
                            ),
                          ),
                        ],
                      ),
                    ),
                    Expanded(child: child),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
}

class _TimelineRow extends StatelessWidget {
  const _TimelineRow({
    required this.time,
    required this.title,
    required this.subtitle,
    required this.isCurrent,
    required this.isFirst,
    required this.isLast,
    required this.onTap,
  });

  final String time;
  final String title;
  final String subtitle;
  final bool isCurrent;
  final bool isFirst;
  final bool isLast;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 44,
                  child: Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      time,
                      style: TextStyle(
                        fontSize: 12,
                        fontFeatures: const [FontFeature.tabularFigures()],
                        fontWeight: FontWeight.w600,
                        color: isCurrent
                            ? const Color(0xff0f766e)
                            : const Color(0xff5b667a),
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 14,
                  child: Stack(
                    alignment: Alignment.topCenter,
                    children: [
                      Positioned(
                        top: isFirst ? 16 : 0,
                        bottom: isLast ? null : 0,
                        height: isLast ? 16 : null,
                        child: Container(
                          width: 2,
                          color: const Color(0x1a0f172a),
                        ),
                      ),
                      Positioned(
                        top: 11,
                        child: Container(
                          width: 10,
                          height: 10,
                          decoration: BoxDecoration(
                            color: const Color(0xff0f766e),
                            shape: BoxShape.circle,
                            border: Border.all(color: Colors.white, width: 2),
                            boxShadow: [
                              BoxShadow(
                                color: const Color(0xffe6f4f1),
                                spreadRadius: isCurrent ? 4 : 2,
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(top: 6, bottom: 18),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          title,
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: isCurrent
                                ? const Color(0xff0f766e)
                                : const Color(0xff0c1222),
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          subtitle,
                          style: const TextStyle(
                            fontSize: 12,
                            color: Color(0xff5b667a),
                          ),
                        ),
                        if (isCurrent) ...[
                          const SizedBox(height: 6),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 2),
                            decoration: BoxDecoration(
                              color: const Color(0xffe6f4f1),
                              borderRadius: BorderRadius.circular(999),
                            ),
                            child: const Text(
                              '当前',
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w700,
                                color: Color(0xff0f766e),
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
