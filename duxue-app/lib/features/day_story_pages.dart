import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import '../core/cue_notifications.dart';
import '../providers.dart';
import '../shared/app_ui.dart';
import '../shared/voice_composer.dart';
import 'home_task_card.dart';
import 'start_cue_card.dart';
import 'task_status_dialogs.dart';

int chatImageCachePixels(double logicalPixels, double devicePixelRatio) {
  final pixels = (logicalPixels * devicePixelRatio).ceil();
  if (pixels < 1) return 1;
  if (pixels > 4096) return 4096;
  return pixels;
}

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

class PickedChatImage {
  const PickedChatImage({required this.bytes, required this.extension});
  final Uint8List bytes;
  final String extension;
}

class _StagedImage {
  _StagedImage({required this.bytes, required this.extension});
  final Uint8List bytes;
  final String extension;
  String? key;
  bool failed = false;
}

class WardDayPage extends ConsumerStatefulWidget {
  const WardDayPage({required this.wardId, super.key, this.pickChatImage});
  final String wardId;

  /// Gallery picker. Tests supply bytes directly; production uses the camera roll.
  final Future<PickedChatImage?> Function()? pickChatImage;
  @override
  ConsumerState<WardDayPage> createState() => _WardDayPageState();
}

class _WardDayPageState extends ConsumerState<WardDayPage> with WidgetsBindingObserver {
  List<dynamic> tasks = [];
  Map<String, dynamic>? plan, insight, profile, startCue;
  String? session;
  int tab = 0;
  final watch = Stopwatch();
  final planAttachments = <String>[];
  final stagedImages = <_StagedImage>[];
  final draftText = TextEditingController();
  List<Map<String, dynamic>> planDraft = [];
  final planMessages = <_ChatLine>[];
  final rememberedImages = <String, Uint8List>{};
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
  Timer? cueRefresh;
  int savedSeconds = 0;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    draftText.addListener(() {
      if (mounted) setState(() {});
    });
    _load();
    _restoreCompanionThread();
    cueRefresh = Timer.periodic(const Duration(minutes: 1), (_) => _refreshCue());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    cueRefresh?.cancel();
    draftText.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refreshCue();
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
      ListView(
          padding: EdgeInsets.fromLTRB(
              16, 14, 16, stagedImages.isNotEmpty ? 292 : 220),
          children: [
            _homeGreeting(context),
            if (startCue?['status'] == 'presented')
              StartCueCard(
                text: startCue?['text'] as String? ?? '',
                tasks: [
                  for (final task in (startCue?['tasks'] as List?) ?? const [])
                    Map<String, dynamic>.from(task as Map),
                ],
                actions: [
                  for (final action in (startCue?['actions'] as List?) ?? const [])
                    Map<String, dynamic>.from(action as Map),
                ],
                onCommand: _actOnStartCue,
              ),
            _contextHeader(
                plan?['status'] == 'confirmed' ? '已确认 · 今日计划' : '今日计划',
                action: planned.isEmpty ? null : _openPlanList,
                actionLabel: '全部'),
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
                  fontSize: 12, color: Color(0xff8b95a8), letterSpacing: 0.2)),
          const SizedBox(height: 4),
          Text('晚上好，${profile?['display_name'] ?? '同学'}',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700, color: const Color(0xff0c1222))),
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
                  style:
                      const TextStyle(fontSize: 12, color: Color(0xff8b95a8))),
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
            final isCurrent = _isItemCurrent(item);
            final startTime = _formatItemStartTime(item, index, planned);
            final durationText = _formatPlannedDuration(item);
            final title = item['title'] as String? ?? '计划项';

            return SizedBox(
                width: 148,
                child: Material(
                    color: Colors.transparent,
                    child: InkWell(
                        borderRadius: BorderRadius.circular(16),
                        onTap: () => _taskTapped(item, true),
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
                                  Text(
                                      homeTaskCardLabel(homeTaskCardKind(item)),
                                      style: TextStyle(
                                          fontSize: 10,
                                          fontWeight: FontWeight.w700,
                                          color: isCurrent
                                              ? const Color(0xff0f766e)
                                              : const Color(0xff8b95a8))),
                                ])))));
          }));

  Widget _poolTask(Map<String, dynamic> item) {
    final kind = homeTaskCardKind(item);
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
                          text: homeTaskCardLabel(kind),
                          color: switch (kind) {
                            HomeTaskCardKind.unscheduled => Colors.deepPurple,
                            HomeTaskCardKind.paused => Colors.orange,
                            HomeTaskCardKind.completed => Colors.blueGrey,
                            HomeTaskCardKind.scheduled ||
                            HomeTaskCardKind.inProgress =>
                              brandBlue,
                          }),
                    ])))));
  }

  bool get _canSendDraft {
    if (planSending) return false;
    if (stagedImages.any((image) => image.key == null && !image.failed)) {
      return false;
    }
    return draftText.text.trim().isNotEmpty ||
        stagedImages.any((image) => image.key != null);
  }

  Widget _chatEntry() => AppCard(
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 10),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        if (stagedImages.isNotEmpty) ...[
          _stagedImageStrip(),
          const SizedBox(height: 8),
        ],
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(
              child: TextField(
                  controller: draftText,
                  enabled: !planSending,
                  minLines: 1,
                  maxLines: 4,
                  textInputAction: TextInputAction.newline,
                  decoration: const InputDecoration(
                      hintText: '补充一句，或直接发送图片',
                      border: InputBorder.none,
                      isDense: true,
                      contentPadding:
                          EdgeInsets.symmetric(horizontal: 4, vertical: 10)))),
          IconButton(
              tooltip: '发送',
              onPressed: _canSendDraft ? () => _sendDraft() : null,
              style: IconButton.styleFrom(
                  backgroundColor: _canSendDraft
                      ? const Color(0xff0f766e)
                      : const Color(0xffe2e8f0),
                  foregroundColor:
                      _canSendDraft ? Colors.white : const Color(0xff94a3b8),
                  disabledBackgroundColor: const Color(0xffe2e8f0),
                  minimumSize: const Size(36, 36),
                  padding: EdgeInsets.zero),
              icon: const Icon(Icons.arrow_upward, size: 18)),
        ]),
        VoiceComposer(
            baseUrl: apiBaseUrl,
            tokens: ref.read(tokenStorageProvider),
            telemetry: ref.read(telemetryProvider),
            holdToTalkText: '说出你的任何想法、问题、安排',
            helperText: '按住说话',
            enabled: !planSending,
            onTap: _openPlanChat,
            onBeforeRecording: () => ref.read(apiProvider).ensureValidAccess(),
            onPickImage: _pickPlanImage,
            onVoiceFinal: (text) => _sendDraft(spoken: text)),
      ]));

  Widget _stagedImageStrip() => SizedBox(
      key: const Key('staged-image-strip'),
      height: 64,
      child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: stagedImages.length,
          separatorBuilder: (_, __) => const SizedBox(width: 8),
          itemBuilder: (_, index) {
            final image = stagedImages[index];
            return Stack(children: [
              ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: Image.memory(image.bytes,
                      width: 56,
                      height: 56,
                      fit: BoxFit.cover,
                      cacheWidth: chatImageCachePixels(
                          56, MediaQuery.devicePixelRatioOf(context)),
                      cacheHeight: chatImageCachePixels(
                          56, MediaQuery.devicePixelRatioOf(context)),
                      gaplessPlayback: true)),
              if (image.key == null || image.failed)
                Positioned.fill(
                    child: DecoratedBox(
                        decoration: BoxDecoration(
                            color: const Color(0x990c1222),
                            borderRadius: BorderRadius.circular(10)),
                        child: Icon(
                            image.failed
                                ? Icons.error_outline
                                : Icons.hourglass_top,
                            color: Colors.white,
                            size: 18))),
              Positioned(
                  top: 2,
                  right: 2,
                  child: IconButton(
                      tooltip: '移除图片',
                      visualDensity: VisualDensity.compact,
                      padding: EdgeInsets.zero,
                      constraints:
                          const BoxConstraints.tightFor(width: 22, height: 22),
                      style: IconButton.styleFrom(
                          backgroundColor: const Color(0xff0c1222),
                          foregroundColor: Colors.white,
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap),
                      onPressed: planSending
                          ? null
                          : () => setState(() => stagedImages.remove(image)),
                      icon: const Icon(Icons.close, size: 14))),
            ]);
          }));

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
                final isCurrent = _isItemCurrent(item);
                final time = _formatItemStartTime(item, index, planned);
                final subtitle = _formatPlanItemSubtitle(item);
                final title = item['title'] as String? ?? '计划项';

                return _TimelineRow(
                    time: time,
                    title: title,
                    subtitle: subtitle,
                    statusLabel: homeTaskCardLabel(homeTaskCardKind(item)),
                    isCurrent: isCurrent,
                    isFirst: index == 0,
                    isLast: index == planned.length - 1,
                    onTap: () {
                      setState(() => planListOpen = false);
                      _taskTapped(item, true);
                    });
              }));

  bool _isItemCurrent(Map<String, dynamic> item) {
    return homeTaskCardKind(item) == HomeTaskCardKind.inProgress;
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
                final mins = (planned[k]
                        as Map<String, dynamic>)['planned_minutes'] as num? ??
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
      final mins =
          (planned[i] as Map<String, dynamic>)['planned_minutes'] as num? ?? 30;
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
      bottomInset: stagedImages.isNotEmpty ? 230 : 148,
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
          _ChatBubble(
              label: message.label,
              text: message.content,
              images: message.images),
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

  Future<void> _sendDraft({String? spoken}) async {
    if (planSending) return;
    if (stagedImages.any((image) => image.key == null && !image.failed)) {
      showMessage(context, '图片还在上传，请稍候再发送');
      return;
    }
    final text = (spoken ?? draftText.text).trim();
    final hasImage = stagedImages.any((image) => image.key != null);
    if (text.isEmpty && !hasImage) {
      if (stagedImages.any((image) => image.failed)) {
        showMessage(context, '图片上传失败，请移除后重试');
      }
      return;
    }
    final content = text.isEmpty ? '请看这张图片。' : text;
    final images = [
      for (final image in stagedImages)
        if (image.key != null) image.bytes,
    ];
    _openPlanChat();
    setState(() => planMessages
        .add(_ChatLine(label: '我', content: content, images: images)));
    if (spoken == null) draftText.clear();
    await _submitPlanInput(content);
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
    try {
      startCue = await ref.read(apiProvider).currentStartCue();
      await CueNotifications.replace(startCue?['notifications']);
    } catch (_) {
      startCue = null;
    }
    if (mounted) setState(() {});
  }

  Future<void> _refreshCue() async {
    try {
      final cue = await ref.read(apiProvider).currentStartCue();
      if (!mounted) return;
      setState(() => startCue = cue);
      await CueNotifications.replace(cue['notifications']);
    } catch (_) {}
  }

  Future<void> _actOnStartCue(String command) async {
    final cueId = startCue?['id'] as String?;
    final version = startCue?['version'] as int?;
    if (cueId == null || version == null) return;
    try {
      await ref.read(apiProvider).actOnStartCue(cueId, command, version);
      await _load();
    } catch (error) {
      if (mounted) showMessage(context, '操作没有完成，请稍后再试：$error');
    }
  }

  Future<void> _confirmLogout() async {
    final approved = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(20)),
                backgroundColor: Colors.white,
                surfaceTintColor: Colors.transparent,
                titlePadding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
                contentPadding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
                actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                title: const Text('退出此设备绑定？',
                    style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                        color: Color(0xff0c1222))),
                content: const Text('之后需要用新的绑定码才能再次进入学习空间。',
                    style: TextStyle(
                        fontSize: 13, color: Color(0xff64748b), height: 1.4)),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(dialogContext, false),
                      style: TextButton.styleFrom(
                          foregroundColor: const Color(0xff64748b)),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(dialogContext, true),
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xff0f766e),
                        foregroundColor: Colors.white,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10)),
                      ),
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
    final kind = homeTaskCardKind(item);
    final rawSession = item['session'];
    final data =
        rawSession is Map ? Map<String, dynamic>.from(rawSession) : null;
    if (kind == HomeTaskCardKind.completed) {
      return;
    }
    if (kind == HomeTaskCardKind.inProgress && data != null) {
      return _showActiveActions(item, data);
    }
    if (kind == HomeTaskCardKind.paused && data != null) {
      final sessionId = data['id'] as String;
      final seconds = data['active_seconds'] as int? ?? 0;
      return _showPausedActions(item, sessionId, seconds);
    }
    await _showStartTaskDialog(item, planned);
  }

  Future<void> _showStartTaskDialog(
      Map<String, dynamic> item, bool planned) async {
    final taskTitle = item['title'] as String? ?? '当前任务';
    final durationText = _formatPlannedDuration(item);
    final details = item['details'] as String?;
    final approved = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => StartTaskDialog(
              taskTitle: taskTitle,
              isPlanned: planned,
              durationText: durationText,
              details: details,
            ));
    if (approved != true) return;
    try {
      final result = planned
          ? await ref.read(apiProvider).startSession(item['id'] as String)
          : await ref
              .read(apiProvider)
              .startAssignmentSession(item['id'] as String);
      final sessionId = result['id'] as String;
      final seconds = result['active_seconds'] as int? ?? 0;
      _patchTaskSession(item['id'] as String, {
        'id': sessionId,
        'status': 'active',
        'active_seconds': seconds,
      });
      _trackSession(sessionId, seconds);
      await _load();
    } catch (error) {
      if (mounted) showMessage(context, '操作没有完成，请稍后再试：$error');
    }
  }

  int _secondsFor(Map<String, dynamic> data) {
    final id = data['id'] as String?;
    if (id != null && id == session) return _elapsedSeconds;
    return data['active_seconds'] as int? ?? 0;
  }

  Future<void> _showActiveActions(
      Map<String, dynamic> item, Map<String, dynamic> data) {
    final taskId = item['id'] as String;
    final taskTitle = item['title'] as String? ?? '当前任务';
    final sessionId = data['id'] as String;
    final seconds = _secondsFor(data);
    final details = item['details'] as String?;
    return showDialog<void>(
        context: context,
        builder: (dialogContext) => ActiveTaskDialog(
              taskTitle: taskTitle,
              seconds: seconds,
              details: details,
              onPause: () {
                Navigator.pop(dialogContext);
                _pauseSession(taskId, sessionId, seconds);
              },
              onFinish: () {
                Navigator.pop(dialogContext);
                _confirmFinishTask(taskTitle, taskId, sessionId, seconds);
              },
            ));
  }

  Future<void> _showPausedActions(
      Map<String, dynamic> item, String sessionId, int seconds) async {
    final taskId = item['id'] as String;
    final taskTitle = item['title'] as String? ?? '当前任务';
    final details = item['details'] as String?;
    final action = await showDialog<String>(
        context: context,
        builder: (dialogContext) => PausedTaskDialog(
              taskTitle: taskTitle,
              seconds: seconds,
              details: details,
            ));
    if (action == 'resume') {
      await _resumeSession(taskId, sessionId, seconds);
    } else if (action == 'finish') {
      await _confirmFinishTask(taskTitle, taskId, sessionId, seconds);
    }
  }

  Future<void> _confirmFinishTask(
      String taskTitle, String taskId, String sessionId, int seconds) async {
    final approved = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => FinishTaskConfirmDialog(
              taskTitle: taskTitle,
              seconds: seconds,
            ));
    if (approved != true) return;
    await _finishSession(taskId, sessionId, seconds, taskTitle: taskTitle);
  }

  void _patchTaskSession(String taskId, Map<String, dynamic>? session) {
    tasks = [
      for (final raw in tasks)
        if (raw is Map && raw['id'] == taskId)
          {...Map<String, dynamic>.from(raw), 'session': session}
        else
          raw,
    ];
    final items = plan?['items'];
    if (items is List) {
      plan = {
        ...plan!,
        'items': [
          for (final raw in items)
            if (raw is Map &&
                (raw['id'] == taskId || raw['assignment_id'] == taskId))
              {...Map<String, dynamic>.from(raw), 'session': session}
            else
              raw,
        ],
      };
    }
    setState(() {});
  }

  void _trackSession(String sessionId, int seconds) {
    session = sessionId;
    savedSeconds = seconds;
    watch
      ..reset()
      ..start();
    timer?.cancel();
    timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  void _clearTrackedSession(String sessionId) {
    if (session != sessionId) return;
    watch.stop();
    timer?.cancel();
    session = null;
    savedSeconds = 0;
  }

  Future<void> _pauseSession(
      String taskId, String sessionId, int seconds) async {
    final previous = {
      'id': sessionId,
      'status': 'active',
      'active_seconds': seconds,
    };
    _clearTrackedSession(sessionId);
    _patchTaskSession(taskId, {
      'id': sessionId,
      'status': 'paused',
      'active_seconds': seconds,
    });
    try {
      await ref.read(apiProvider).pauseSession(sessionId, seconds);
      await _load();
    } catch (error) {
      if (!mounted) return;
      _patchTaskSession(taskId, previous);
      _trackSession(sessionId, seconds);
      showMessage(context, '操作没有完成，请稍后再试：$error');
    }
  }

  Future<void> _resumeSession(
      String taskId, String sessionId, int seconds) async {
    _patchTaskSession(taskId, {
      'id': sessionId,
      'status': 'active',
      'active_seconds': seconds,
    });
    _trackSession(sessionId, seconds);
    try {
      await ref.read(apiProvider).resumeSession(sessionId);
      await _load();
    } catch (error) {
      if (!mounted) return;
      _clearTrackedSession(sessionId);
      _patchTaskSession(taskId, {
        'id': sessionId,
        'status': 'paused',
        'active_seconds': seconds,
      });
      showMessage(context, '操作没有完成，请稍后再试：$error');
    }
  }

  Future<void> _finishSession(String taskId, String sessionId, int seconds,
      {String? taskTitle}) async {
    _clearTrackedSession(sessionId);
    _patchTaskSession(taskId, null);
    try {
      await ref.read(apiProvider).finishSession(sessionId, seconds);
      if (mounted && taskTitle != null) {
        final minutes = seconds ~/ 60;
        showMessage(context, '🎉 已完成「$taskTitle」，本次学习累计 $minutes 分钟！');
      }
      await _load();
    } catch (error) {
      if (!mounted) return;
      _patchTaskSession(taskId, {
        'id': sessionId,
        'status': 'active',
        'active_seconds': seconds,
      });
      _trackSession(sessionId, seconds);
      showMessage(context, '操作没有完成，请稍后再试：$error');
    }
  }

  Future<PickedChatImage?> _defaultPickChatImage() async {
    final image = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      imageQuality: 85,
      maxWidth: 1600,
      maxHeight: 1600,
    );
    if (image == null) return null;
    final extension = image.name.split('.').last.toLowerCase();
    return PickedChatImage(
        bytes: await image.readAsBytes(), extension: extension);
  }

  Future<void> _pickPlanImage() async {
    _openPlanChat();
    if (stagedImages.length >= 8) {
      showMessage(context, '一次最多添加 8 张图片');
      return;
    }
    final image = await (widget.pickChatImage ?? _defaultPickChatImage)();
    if (image == null || !mounted) return;
    if (!const {'jpg', 'jpeg', 'png', 'webp'}.contains(image.extension)) {
      showMessage(context, '暂只支持 JPG、PNG 或 WebP 图片');
      return;
    }
    final staged = _StagedImage(bytes: image.bytes, extension: image.extension);
    setState(() => stagedImages.add(staged));
    try {
      final key = await ref
          .read(apiProvider)
          .uploadCompanionAttachment(image.bytes, image.extension);
      if (!mounted || !stagedImages.contains(staged)) return;
      setState(() {
        staged.key = key;
        rememberedImages[key] = staged.bytes;
      });
    } catch (_) {
      if (!mounted || !stagedImages.contains(staged)) return;
      setState(() => staged.failed = true);
      showMessage(context, '图片上传失败，请重试');
    }
  }

  Future<void> _submitPlanInput(String text) async {
    if (planSending) return;
    planAttachments
      ..clear()
      ..addAll([
        for (final image in stagedImages)
          if (image.key != null) image.key!,
      ]);
    setState(() => planSending = true);
    try {
      final result = await ref.read(apiProvider).companionTurn(
          content: text,
          threadId: companionThreadId,
          expectedThreadVersion: companionThreadVersion,
          attachmentKeys: List<String>.from(planAttachments));
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
        stagedImages.clear();
        planAttachments.clear();
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
          final refs = (item['attachment_refs'] as List? ?? const [])
              .whereType<String>();
          return _ChatLine(
              label: item['author_type'] == 'ward' ? '我' : '读学 AI',
              content: item['content'] as String,
              images: [
                for (final ref in refs)
                  if (rememberedImages[ref] != null) rememberedImages[ref]!,
              ]);
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
    this.bottomInset = 82,
  });
  final String title;
  final String subtitle;
  final VoidCallback onClose;
  final Widget child;
  final double bottomInset;

  @override
  Widget build(BuildContext context) => Positioned.fill(
      child: ColoredBox(
          color: const Color(0x660c1222),
          child: SafeArea(
              child: Padding(
                  padding: EdgeInsets.fromLTRB(10, 10, 10, bottomInset),
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

class _ChatLine {
  const _ChatLine(
      {required this.label, required this.content, this.images = const []});
  final String label;
  final String content;
  final List<Uint8List> images;
}

class _ChatBubble extends StatelessWidget {
  const _ChatBubble(
      {required this.label, required this.text, this.images = const []});
  final String label;
  final String text;
  final List<Uint8List> images;

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
              if (images.isNotEmpty) ...[
                const SizedBox(height: 6),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  for (var index = 0; index < images.length; index++)
                    ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: Image.memory(images[index],
                            key: ValueKey('sent-chat-image-$index'),
                            width: 72,
                            height: 72,
                            fit: BoxFit.cover,
                            cacheWidth: chatImageCachePixels(
                                72, MediaQuery.devicePixelRatioOf(context)),
                            cacheHeight: chatImageCachePixels(
                                72, MediaQuery.devicePixelRatioOf(context)),
                            gaplessPlayback: true)),
                ]),
              ],
              if (text.isNotEmpty &&
                  !(images.isNotEmpty && text == '请看这张图片。')) ...[
                const SizedBox(height: 4),
                Text(text),
              ],
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
    required this.statusLabel,
    required this.isCurrent,
    required this.isFirst,
    required this.isLast,
    required this.onTap,
  });

  final String time;
  final String title;
  final String subtitle;
  final String statusLabel;
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
                        const SizedBox(height: 6),
                        Text(
                          statusLabel,
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                            color: isCurrent
                                ? const Color(0xff0f766e)
                                : const Color(0xff8b95a8),
                          ),
                        ),
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
