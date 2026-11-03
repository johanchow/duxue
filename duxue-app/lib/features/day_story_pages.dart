import 'dart:async';
import 'dart:math';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import '../core/cue_notifications.dart';
import '../core/cue_refresh_schedule.dart';
import '../core/speech_playback.dart';
import '../core/voice_transcription_service.dart';
import '../core/user_error_message.dart';
import '../providers.dart';
import '../shared/app_ui.dart';
import '../shared/chat_markdown.dart';
import '../shared/voice_composer.dart';
import 'home_task_card.dart';
import 'guardian_report_view.dart';
import 'sprint_card.dart';
import 'chat_image_viewer.dart';
import 'pronunciation_player.dart';
import 'start_cue_card.dart';
import 'visual_block.dart';
import 'task_status_dialogs.dart';

const ImageSource defaultChatImageSource = ImageSource.camera;

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
  return '绑定已完成，但这台设备未能保存登录状态；请重试或重启 App。';
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
                enabled: !loading,
                keyboardType: TextInputType.number,
                textInputAction: TextInputAction.done,
                maxLength: 6,
                decoration: const InputDecoration(
                    labelText: '家长提供的 6 位绑定码', hintText: '输入 6 位数字自动进入'),
                onChanged: (value) {
                  if (value.trim().length == 6 && !loading) {
                    _bind();
                  }
                },
                onSubmitted: (_) => _bind()),
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

class GuardianStoryPage extends StatelessWidget {
  const GuardianStoryPage({required this.wardId, super.key});
  final String wardId;
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('学习报告')),
        body: GuardianReportView(wardId: wardId),
      );
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
  const WardDayPage({
    required this.wardId,
    super.key,
    this.pickChatImage,
    this.speechPlayback,
    this.voiceFactory = VoiceTranscriptionService.new,
  });
  final String wardId;

  /// Camera capture. Tests supply bytes directly; production uses the camera.
  final Future<PickedChatImage?> Function()? pickChatImage;

  /// 播放器。测试注入替身；正式环境用设备播放与系统朗读。
  final SpeechPlayback Function()? speechPlayback;

  /// 语音转写替身注入。
  final VoiceTranscriptionFactory voiceFactory;
  @override
  ConsumerState<WardDayPage> createState() => _WardDayPageState();
}

class _WardDayPageState extends ConsumerState<WardDayPage>
    with WidgetsBindingObserver {
  List<dynamic> tasks = [];
  Map<String, dynamic>? plan, insight, profile, startCue;
  String? session;
  Map<String, dynamic>? sprint, readySprint, sprintAction;
  String? hiddenSprintId;
  bool sprintBusy = false;
  int sprintGeneration = 0;
  bool sprintForeground = true;
  Timer? sprintRefresh;
  Map<String, dynamic>? pendingSprintRequest;
  bool sprintSetupOpen = false;
  bool sprintPreviewBusy = false;
  int sprintSetupGeneration = 0;
  Map<String, dynamic>? spokenSprintDraft, spokenSprintPreview;
  String sprintSetupMessage = '这轮想做什么，试多久？说给我听。';
  String? failedSprintSpeech;
  bool? recordingForSprint;
  int? recordingSetupGeneration;
  int tab = 0;
  final watch = Stopwatch();
  final planAttachments = <String>[];
  final stagedImages = <_StagedImage>[];
  List<Map<String, dynamic>> planDraft = [];
  List<Map<String, dynamic>> planAdviceItems = [];
  final planMessages = <_ChatLine>[];
  final historyMessages = <_ChatLine>[];
  final rememberedImages = <String, Uint8List>{};
  final _imageLoads = <String, Future<Uint8List>>{};
  final ScrollController _chatScrollController = ScrollController();
  String? companionThreadId;
  int? companionThreadVersion;
  int? nextBeforeThreadVersion;
  String? previousThreadId;
  String? historyCursorThreadId;
  bool loadingOlderMessages = false;
  String? planFeedback;
  String? planInteractionKind;
  Map<String, dynamic>? planConfirmAction;
  Map<String, dynamic>? planSuggestionAction, planClarifyAction;
  List<Map<String, dynamic>> planClarificationSlots = [];
  final dismissedPlanSuggestions = <String>{};
  String? planDraftId;
  int? planDraftVersion;
  String? failedPlanText;
  List<Map<String, dynamic>> pronunciationLessons = const [];
  SpeechPlayback? _speechPlayback;
  bool planSending = false;
  bool clearingHistory = false;
  bool get _chatBusy => planSending || clearingHistory;
  int _chatGeneration = 0;
  String? _pendingClearCommand;

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
    _chatScrollController.addListener(_onChatScroll);
    _load();
    _restoreCompanionThread();
    _scheduleCueRefresh();
    sprintRefresh =
        Timer.periodic(const Duration(seconds: 30), (_) => _refreshSprint());
  }

  void _scheduleCueRefresh() {
    cueRefresh?.cancel();
    cueRefresh = Timer(nextCueRefreshDelay(DateTime.now()), () {
      if (!mounted) return;
      _refreshCue();
      _scheduleCueRefresh();
    });
  }

  SpeechPlayback _playback() =>
      _speechPlayback ??= (widget.speechPlayback ?? DeviceSpeechPlayback.new)();

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _chatScrollController.dispose();
    timer?.cancel();
    cueRefresh?.cancel();
    sprintRefresh?.cancel();
    _speechPlayback?.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    sprintForeground = state == AppLifecycleState.resumed;
    sprintGeneration++;
    if (state == AppLifecycleState.resumed) {
      setState(() => sprint = null);
      _refreshSprint();
      _refreshCue();
      _scheduleCueRefresh();
    }
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
          onDestinationSelected: (value) => setState(() {
                if (value != 0) _discardSprintSetup();
                tab = value;
              }),
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
    return Stack(children: [
      if (planListOpen)
        _planListOverlay(planned)
      else if (planChatOpen)
        _planChatOverlay()
      else
        _quietHome(),
      if (!planListOpen)
        Positioned(left: 16, right: 16, bottom: 12, child: _chatEntry()),
    ]);
  }

  Widget _homeMenu() => PopupMenuButton<String>(
        tooltip: '更多',
        onSelected: (value) {
          switch (value) {
            case 'tasks':
              _openPlanList();
            case 'history':
              _openPlanChat();
            case 'sprint':
              _openSprint();
            case 'clear':
              _clearChatHistory();
          }
        },
        itemBuilder: (_) => const [
          PopupMenuItem(value: 'tasks', child: Text('作业')),
          PopupMenuItem(value: 'history', child: Text('历史对话')),
          PopupMenuItem(value: 'sprint', child: Text('专注挑战')),
          PopupMenuItem(value: 'clear', child: Text('清空历史对话')),
        ],
      );

  Widget? _activeSprintCard() =>
      sprint != null && hiddenSprintId != sprint!['id']
          ? SprintCard(
              sprint: sprint!,
              busy: sprintBusy,
              onAction: _actSprint,
              onHide: () =>
                  setState(() => hiddenSprintId = sprint!['id'] as String),
              onElapsed: _refreshSprint)
          : null;

  Widget _quietHome() => Positioned.fill(
          child: Column(children: [
        Padding(
            padding: const EdgeInsets.fromLTRB(20, 8, 8, 8),
            child: Row(children: [
              const Expanded(
                  child: Text('读学',
                      style: TextStyle(
                          fontSize: 20, fontWeight: FontWeight.w700))),
              _homeMenu(),
            ])),
        Expanded(
            child: SingleChildScrollView(
                padding: EdgeInsets.fromLTRB(
                    20, 24, 20, stagedImages.isNotEmpty ? 184 : 112),
                child: Column(children: [
                  if (sprintSetupOpen)
                    _spokenSprintCard()
                  else ...[
                    if (_activeSprintCard() case final card?)
                      card
                    else ...[
                      const SizedBox(height: 40),
                      const Icon(Icons.menu_book_outlined,
                          size: 38, color: Color(0xff0f766e)),
                      const SizedBox(height: 18),
                      const Text('先做手边的一小步',
                          style: TextStyle(
                              fontSize: 23, fontWeight: FontWeight.w600)),
                      const SizedBox(height: 8),
                      const Text('有问题，随时找我。',
                          style: TextStyle(color: Colors.blueGrey)),
                      const SizedBox(height: 28),
                      Tooltip(
                          message: '专注挑战',
                          child: OutlinedButton.icon(
                              onPressed: sprintBusy ? null : _openSprint,
                              icon: const Icon(Icons.timer_outlined),
                              label:
                                  Text(sprint == null ? '试一轮专注挑战' : '查看本轮挑战'))),
                    ],
                    if (startCue?['status'] == 'presented') ...[
                      const SizedBox(height: 20),
                      StartCueCard(
                          text: startCue?['text'] as String? ?? '',
                          tasks: [
                            for (final row in startCue?['tasks'] as List? ?? [])
                              Map<String, dynamic>.from(row as Map)
                          ],
                          actions: [
                            for (final row
                                in startCue?['actions'] as List? ?? [])
                              Map<String, dynamic>.from(row as Map)
                          ],
                          onCommand: _actOnStartCue),
                    ],
                    if (historyMessages.isNotEmpty ||
                        planMessages.isNotEmpty ||
                        _hasOlderHistory) ...[
                      const SizedBox(height: 24),
                      TextButton.icon(
                          onPressed: _openPlanChat,
                          icon: const Icon(Icons.chat_bubble_outline, size: 16),
                          label: const Text('继续上次对话')),
                    ],
                  ],
                ]))),
      ]));

  Widget _spokenSprintCard() => AppCard(
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Expanded(
              child: Text('试一轮专注挑战',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700))),
          TextButton(
              onPressed:
                  sprintBusy ? null : () => setState(_discardSprintSetup),
              child: const Text('先不用')),
        ]),
        const SizedBox(height: 12),
        Text(sprintSetupMessage, style: const TextStyle(height: 1.6)),
        if (sprintPreviewBusy)
          const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: LinearProgressIndicator()),
        if (failedSprintSpeech != null)
          TextButton(
              onPressed: sprintPreviewBusy
                  ? null
                  : () => _previewSpokenSprint(failedSprintSpeech!),
              child: const Text('重试整理')),
        if (spokenSprintPreview?['status'] == 'ready' &&
            !sprintPreviewBusy) ...[
          const SizedBox(height: 20),
          Wrap(spacing: 12, children: [
            FilledButton(
                onPressed: sprintBusy ? null : _startSpokenSprint,
                child: Text(sprintBusy ? '开启中…' : '开始本轮')),
            TextButton(
                onPressed: sprintBusy
                    ? null
                    : () => setState(() {
                          sprintSetupGeneration++;
                          spokenSprintPreview = null;
                          failedSprintSpeech = null;
                          sprintSetupMessage = '想改哪里？按住下面的说话按钮，再说一次。';
                        }),
                child: const Text('重新说')),
          ]),
        ],
      ]));

  void _discardSprintSetup() {
    sprintSetupGeneration++;
    sprintSetupOpen = false;
    sprintPreviewBusy = false;
    spokenSprintDraft = spokenSprintPreview = null;
    failedSprintSpeech = null;
    pendingSprintRequest = null;
  }

  Future<void> _previewSpokenSprint(String speech) async {
    if (!sprintSetupOpen ||
        sprintPreviewBusy ||
        sprintBusy ||
        speech.trim().isEmpty) {
      return;
    }
    final generation = ++sprintSetupGeneration;
    setState(() {
      sprintPreviewBusy = true;
      failedSprintSpeech = null;
      spokenSprintPreview = null;
    });
    try {
      final result = await ref
          .read(apiProvider)
          .previewSprint(speech, previous: spokenSprintDraft);
      if (!mounted || generation != sprintSetupGeneration || !sprintSetupOpen) {
        return;
      }
      if (result['status'] == 'cancelled') {
        setState(_discardSprintSetup);
        return;
      }
      setState(() {
        spokenSprintPreview = result;
        spokenSprintDraft = {
          'topic': result['topic'],
          'target_minutes': result['target_minutes']
        };
        sprintSetupMessage = result['message'] as String? ?? '想试多久？';
      });
    } catch (_) {
      if (!mounted || generation != sprintSetupGeneration || !sprintSetupOpen) {
        return;
      }
      setState(() {
        failedSprintSpeech = speech;
        sprintSetupMessage = '这次没有整理成功，可以再试一次。';
      });
    } finally {
      if (mounted && generation == sprintSetupGeneration && sprintSetupOpen) {
        setState(() => sprintPreviewBusy = false);
      }
    }
  }

  bool get _canSendDraft {
    if (_chatBusy) return false;
    if (stagedImages.any((image) => image.key == null && !image.failed)) {
      return false;
    }
    return stagedImages.any((image) => image.key != null);
  }

  Future<void> _beforeHomeRecording() async {
    recordingForSprint = sprintSetupOpen;
    recordingSetupGeneration = sprintSetupGeneration;
    await ref.read(apiProvider).ensureValidAccess();
  }

  Future<void> _onHomeVoiceFinal(String text) async {
    final wasSprint = recordingForSprint;
    final setupGeneration = recordingSetupGeneration;
    recordingForSprint = null;
    recordingSetupGeneration = null;
    if (wasSprint != null && setupGeneration != sprintSetupGeneration) return;
    if (wasSprint == true && !sprintSetupOpen) return;
    if (sprintSetupOpen) {
      await _previewSpokenSprint(text);
    } else {
      await _sendDraft(spoken: text);
    }
  }

  Widget _chatEntry() => AppCard(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        if (stagedImages.isNotEmpty) ...[
          Row(children: [
            Expanded(child: _stagedImageStrip()),
            const SizedBox(width: 8),
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
          const SizedBox(height: 8),
        ],
        VoiceComposer(
            baseUrl: apiBaseUrl,
            tokens: ref.read(tokenStorageProvider),
            telemetry: ref.read(telemetryProvider),
            voiceFactory: widget.voiceFactory,
            holdToTalkText: '说出你的任何想法、问题、安排',
            helperText: '按住说话',
            enabled: !_chatBusy && !sprintPreviewBusy && !sprintBusy,
            onTap: sprintSetupOpen ? null : _openPlanChat,
            onBeforeRecording: _beforeHomeRecording,
            onPickImage: _pickPlanImage,
            onVoiceFinal: _onHomeVoiceFinal),
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
                      onPressed: _chatBusy
                          ? null
                          : () => setState(() => stagedImages.remove(image)),
                      icon: const Icon(Icons.close, size: 14))),
            ]);
          }));

  Widget _planListOverlay(List<dynamic> planned) {
    final byId = <String, Map<String, dynamic>>{};
    for (final raw in [...tasks, ...planned]) {
      final row = Map<String, dynamic>.from(raw as Map);
      byId[(row['assignment_id'] ?? row['id']).toString()] = row;
    }
    return _PlanSheetOverlay(
        title: '已知作业',
        subtitle: '按需查看，未确认完成不代表没做',
        onClose: () => setState(() => planListOpen = false),
        child: ListView(children: [
          for (final item in byId.values)
            ListTile(
              title: Text(item['title'] as String? ?? '作业'),
              subtitle: Text(_formatPlannedDuration(item)),
              onTap: () => _taskTapped(
                  item,
                  planned.any((row) =>
                      (row['assignment_id'] ?? row['id']) ==
                      (item['assignment_id'] ?? item['id']))),
              trailing: IconButton(
                  tooltip: '任务操作',
                  icon: const Icon(Icons.more_horiz),
                  onPressed: () => _showTaskActions(item)),
              onLongPress:
                  item['source'] == 'ward' ? () => _removePoolTask(item) : null,
            ),
          if (byId.isEmpty) const ListTile(title: Text('目前没有已登记作业，可以直接学习或提问。')),
        ]));
  }

  Future<void> _showTaskActions(Map<String, dynamic> item) async {
    final action = await showModalBottomSheet<String>(
        context: context,
        builder: (ctx) => SafeArea(
                child: Column(mainAxisSize: MainAxisSize.min, children: [
              for (final entry in const {
                'start': '开始这项',
                'pause': '暂停',
                'resume': '继续',
                'end': '这次先到这里',
                'complete': '这项写完了',
                'time': '查看已记录用时'
              }.entries)
                ListTile(
                    title: Text(entry.value),
                    onTap: () => Navigator.pop(ctx, entry.key)),
            ])));
    if (action == null) return;
    try {
      final result = await ref.read(apiProvider).taskCommand(
          (item['assignment_id'] ?? item['id']).toString(), action);
      if (mounted && action == 'time') {
        final seconds = result['active_seconds'];
        showMessage(
            context,
            seconds == null
                ? '没有可靠执行计时记录'
                : '显式会话计时约 ${(seconds as num) ~/ 60} 分钟，不是净专注时长');
      }
      await _load();
    } catch (error) {
      if (mounted) showMessage(context, userErrorMessage(error));
    }
  }

  String _formatPlannedDuration(Map<String, dynamic> item) {
    final mins = item['planned_minutes'] as num?;
    if (mins != null && mins > 0) {
      return item['duration_kind'] == 'timebox'
          ? '本次打算投入 ${mins.toInt()} 分钟'
          : '预计 ${mins.toInt()} 分钟';
    }
    return '未估时';
  }

  bool get _hasOlderHistory =>
      nextBeforeThreadVersion != null || previousThreadId != null;

  Widget _planReviewCard(List<Map<String, dynamic>> items,
          {required bool active}) =>
      Padding(
        padding: const EdgeInsets.only(top: 14),
        child: AppCard(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('已记录（待你确认）',
              style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          for (final item in items) ...[
            Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text('• ${item['title']} · '
                    '${_draftSlotLabel(item)} · '
                    '${item['planned_minutes'] == null ? '未估时' : '约 ${item['planned_minutes']} 分钟'}')),
            _planSuggestion(item, 'duration',
                showActions: false, honorDismissal: active),
            _planSuggestion(item, 'time',
                showActions: false, honorDismissal: active),
          ],
          if (active) ...[
            const SizedBox(height: 8),
            SizedBox(
                width: double.infinity,
                child: FilledButton(
                    onPressed: _chatBusy || planConfirmAction == null
                        ? null
                        : _confirmPlanDraft,
                    child: const Text('确认这个计划'))),
          ],
        ])),
      );

  Widget _planChatOverlay() {
    final canReviewDraft = planInteractionKind == 'plan_confirm_list' &&
        planConfirmAction != null &&
        planDraft.isNotEmpty;
    final items = <Widget>[
      if (startCue?['status'] == 'presented')
        StartCueCard(
            text: startCue?['text'] as String? ?? '',
            tasks: [
              for (final row in startCue?['tasks'] as List? ?? [])
                Map<String, dynamic>.from(row as Map)
            ],
            actions: [
              for (final row in startCue?['actions'] as List? ?? [])
                Map<String, dynamic>.from(row as Map)
            ],
            onCommand: _actOnStartCue),
      if (sprintAction != null)
        FilledButton(
            onPressed: _chatBusy ? null : _acceptSprintProposal,
            child: const Text('开始这次挑战')),
      if (loadingOlderMessages)
        const Padding(
          padding: EdgeInsets.only(top: 10),
          child: Center(
              child: SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))),
        )
      else if (_hasOlderHistory)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Center(
            child: TextButton.icon(
              key: const Key('load-older-messages-button'),
              onPressed: _loadOlderMessages,
              icon: const Icon(Icons.history, size: 16),
              label: const Text('上滑或点击查看更早对话', style: TextStyle(fontSize: 12)),
            ),
          ),
        ),
      const Padding(
        padding: EdgeInsets.only(top: 14),
        child:
            _ChatBubble(label: '读学 AI', text: '遇到问题随时问我；需要时也可以查看作业，或试一轮专注挑战。'),
      ),
      for (final message in historyMessages) _chatMessage(message),
      for (final message in planMessages) _chatMessage(message),
      if (_chatBusy)
        const Padding(
          padding: EdgeInsets.only(top: 14),
          child: Center(child: CircularProgressIndicator()),
        ),
      if (failedPlanText != null)
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Row(children: [
            const Expanded(
                child: Text('这条消息暂未送达。',
                    style: TextStyle(fontSize: 12, color: Colors.redAccent))),
            TextButton(
                onPressed:
                    _chatBusy ? null : () => _submitPlanInput(failedPlanText!),
                child: const Text('重试')),
          ]),
        ),
      if (canReviewDraft && !_currentMessageCarriesPlanReview)
        _planReviewCard(planDraft, active: true),
      for (final slot in planClarificationSlots)
        if (slot['field'] == 'planned_minutes')
          _planSuggestion(slot, 'clarification'),
      if (planInteractionKind == 'clarify')
        for (final item in planAdviceItems) ...[
          _planSuggestion(item, 'duration'),
          _planSuggestion(item, 'time'),
        ],
      if (!_messagesCarryPronunciation)
        for (final item in pronunciationLessons)
          Padding(
            padding: const EdgeInsets.only(top: 14),
            child: _pronunciationCard(item),
          ),
    ];

    return _HomeOverlay(
      banner: _activeSprintCard(),
      title: '读学',
      subtitle: '随时提问，需要时再安排。',
      bottomInset: stagedImages.isNotEmpty ? 164 : 92,
      onClose: () => setState(() => planChatOpen = false),
      closeTooltip: '收起对话',
      action: _homeMenu(),
      child: ListView.builder(
        key: const Key('companion-chat-list'),
        controller: _chatScrollController,
        padding: const EdgeInsets.all(16),
        itemCount: items.length,
        itemBuilder: (context, index) => items[index],
      ),
    );
  }

  Future<void> _clearChatHistory() async {
    if (clearingHistory) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('清空历史对话？'),
        content: const Text('清空对话列表并重新开始。已保存的任务、计划、学习记录和长期记忆会保留，历史数据仍由系统保存。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('清空并重新开始')),
        ],
      ),
    );
    if (confirmed != true || !mounted || clearingHistory) return;
    _pendingClearCommand ??=
        List.generate(16, (_) => Random.secure().nextInt(256))
            .map((value) => value.toRadixString(16).padLeft(2, '0'))
            .join();
    setState(() => clearingHistory = true);
    var serverCleared = false;
    try {
      await ref.read(apiProvider).clearCompanionHistory(_pendingClearCommand!);
      serverCleared = true;
      if (!mounted) return;
      setState(() {
        _chatGeneration++;
        _pendingClearCommand = null;
        planSending = false;
        planMessages.clear();
        historyMessages.clear();
        rememberedImages.clear();
        _imageLoads.clear();
        stagedImages.clear();
        planAttachments.clear();
        companionThreadId = null;
        companionThreadVersion = null;
        historyCursorThreadId = null;
        nextBeforeThreadVersion = null;
        previousThreadId = null;
        loadingOlderMessages = false;
        _userScrolledAwayFromTop = false;
        planDraft = [];
        planAdviceItems = [];
        planClarificationSlots = [];
        dismissedPlanSuggestions.clear();
        planFeedback = null;
        planInteractionKind = null;
        planConfirmAction = null;
        planSuggestionAction = null;
        planClarifyAction = null;
        planDraftId = null;
        planDraftVersion = null;
        failedPlanText = null;
        pronunciationLessons = const [];
        chatSubject = null;
      });
      await ref.read(tokenStorageProvider).clearCompanionThread();
      await _speechPlayback?.stop();
      if (mounted) showMessage(context, '对话已清空，可以重新开始');
    } catch (_) {
      if (mounted) {
        showMessage(
            context, serverCleared ? '对话已清空，本地同步未完成，请重新打开页面' : '清空失败，请稍后重试');
      }
    } finally {
      if (mounted) setState(() => clearingHistory = false);
    }
  }

  void _openPlanList() => setState(() {
        _discardSprintSetup();
        planChatOpen = false;
        planListOpen = true;
      });

  void _openPlanChat([String? subject]) {
    final wasOpen = planChatOpen;
    setState(() {
      _discardSprintSetup();
      planListOpen = false;
      chatSubject = subject;
      planChatOpen = true;
    });
    if (!wasOpen) {
      _scrollToChatBottom();
    }
  }

  String _draftSlotLabel(Map<String, dynamic> item) {
    final start = DateTime.tryParse(item['start_at'] as String? ?? '');
    final end = DateTime.tryParse(item['end_at'] as String? ?? '');
    String clock(DateTime value) =>
        '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
    if (start == null) return '未排时间';
    return end == null ? '${clock(start)} 开始' : '${clock(start)}–${clock(end)}';
  }

  Future<void> _sendDraft({String? spoken, bool pronunciation = false}) async {
    if (_chatBusy) return;
    if (stagedImages.any((image) => image.key == null && !image.failed)) {
      showMessage(context, '图片还在上传，请稍候再发送');
      return;
    }
    final text = (spoken ?? '').trim();
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
    setState(() {
      _anchorPronunciationLessons();
      _anchorPlanReview();
      planMessages.add(_ChatLine(label: '我', content: content, images: images));
    });
    _scrollToChatBottom();
    await _submitPlanInput(content, pronunciation: pronunciation);
    _scrollToChatBottom();
  }

  Widget _growth(BuildContext context) =>
      ListView(padding: const EdgeInsets.all(16), children: [
        const SectionLabel('今天'),
        TextButton(onPressed: _review, child: const Text('说说今天的感受')),
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
      showMessage(context, '删除失败：${userErrorMessage(error)}');
      await _load();
    }
  }

  String _sprintCommandId() =>
      List.generate(16, (_) => Random.secure().nextInt(256))
          .map((value) => value.toRadixString(16).padLeft(2, '0'))
          .join();

  Future<void> _refreshSprint() async {
    if (!sprintForeground) return;
    final generation = ++sprintGeneration;
    try {
      final result = await ref.read(apiProvider).currentSprint();
      if (!mounted || generation != sprintGeneration || !sprintForeground) {
        return;
      }
      setState(() {
        sprint = result['sprint'] is Map
            ? Map<String, dynamic>.from(result['sprint'] as Map)
            : null;
        readySprint = result['ready'] is Map
            ? Map<String, dynamic>.from(result['ready'] as Map)
            : null;
        if (sprint != null && sprintSetupOpen && !sprintBusy) {
          _discardSprintSetup();
          hiddenSprintId = null;
        }
      });
      final notice = result['notice'];
      if (!_chatBusy && !sprintBusy && notice is Map) {
        try {
          await ref.read(apiProvider).sprintCommand(notice['id'] as String, {
            'command_id': _sprintCommandId(),
            'action': 'claim_notice',
            'expected_version': notice['version']
          });
        } catch (_) {
          return; // Another device may have claimed this notice; keep the verified round.
        }
        if (mounted &&
            !_chatBusy &&
            sprintForeground &&
            generation == sprintGeneration) {
          showMessage(
              context,
              notice['status'] == 'ready'
                  ? '约定的挑战时间到了，想开始时点“专注挑战”。'
                  : '这轮计时结束了，要继续还是休息？');
        }
      }
    } catch (_) {
      // A missing/unavailable query is not evidence a round is still running.
      if (mounted && generation == sprintGeneration) {
        setState(() => sprint = null);
      }
    }
  }

  Future<void> _openSprint() async {
    if (sprintBusy || _chatBusy) return;
    final generation = ++sprintSetupGeneration;
    setState(() {
      planListOpen = planChatOpen = false;
      sprintSetupOpen = true;
      spokenSprintDraft = spokenSprintPreview = null;
      sprintPreviewBusy = false;
      failedSprintSpeech = null;
      sprintSetupMessage = '这轮想做什么，试多久？说给我听。';
      pendingSprintRequest = null;
    });
    await _refreshSprint();
    if (!mounted || generation != sprintSetupGeneration || !sprintSetupOpen) {
      return;
    }
    if (sprint != null) {
      setState(() {
        _discardSprintSetup();
        hiddenSprintId = null;
      });
    }
  }

  Future<void> _startSpokenSprint() async {
    if (!sprintSetupOpen ||
        sprintBusy ||
        spokenSprintPreview?['status'] != 'ready') {
      return;
    }
    final generation = sprintSetupGeneration;
    final selection = Map<String, dynamic>.from(spokenSprintPreview!);
    final target = selection['target_minutes'] as int;
    final chosenTopic = selection['topic'] as String;
    final data = <String, dynamic>{
      'action': 'create',
      'topic': chosenTopic,
      'target_minutes': target
    };
    if (pendingSprintRequest == null ||
        pendingSprintRequest!['topic'] != chosenTopic ||
        pendingSprintRequest!['target_minutes'] != target) {
      pendingSprintRequest = {...data, 'command_id': _sprintCommandId()};
    }
    setState(() => sprintBusy = true);
    try {
      if (readySprint != null &&
          readySprint!['topic'] == chosenTopic &&
          (readySprint!['target_seconds'] as num).toInt() == target * 60) {
        await ref
            .read(apiProvider)
            .sprintCommand(readySprint!['id'] as String, {
          'command_id': pendingSprintRequest!['command_id'],
          'action': 'start',
          'expected_version': readySprint!['version']
        });
      } else {
        await ref.read(apiProvider).createSprint(pendingSprintRequest!);
      }
      hiddenSprintId = null;
      await _refreshSprint();
      if (mounted && generation == sprintSetupGeneration) {
        setState(_discardSprintSetup);
      }
    } catch (error) {
      if (mounted) showMessage(context, '挑战未能开启：${userErrorMessage(error)}');
    } finally {
      if (mounted) setState(() => sprintBusy = false);
    }
  }

  Future<void> _actSprint(String action) async {
    if (sprintBusy || sprint == null) return;
    final row = Map<String, dynamic>.from(sprint!);
    setState(() => sprintBusy = true);
    try {
      await ref.read(apiProvider).sprintCommand(row['id'] as String, {
        'command_id': _sprintCommandId(),
        'action': action,
        'expected_version': row['version']
      });
      await _refreshSprint();
    } catch (error) {
      await _refreshSprint();
      if (mounted) showMessage(context, '操作未完成：${userErrorMessage(error)}');
    } finally {
      if (mounted) setState(() => sprintBusy = false);
    }
  }

  Future<void> _acceptSprintProposal() async {
    final action = sprintAction;
    if (action == null || _chatBusy) return;
    setState(() => planSending = true);
    try {
      final result = await ref.read(apiProvider).companionTurn(
          content: '',
          threadId: companionThreadId,
          expectedThreadVersion: companionThreadVersion,
          routeHint: 'planning',
          structuredCommand: {
            'interaction_id': action['id'],
            'command': 'sprint_command',
            'payload': action['payload']
          });
      if (!mounted) return;
      sprintAction = null;
      await _applyPlanTurnResult(result);
      await _refreshSprint();
    } catch (error) {
      if (mounted) showMessage(context, '请重新查看这轮挑战：${userErrorMessage(error)}');
    } finally {
      if (mounted) setState(() => planSending = false);
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
      await _refreshSprint();
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
      if (mounted) showMessage(context, '操作未完成：${userErrorMessage(error)}');
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
    final expressionController = TextEditingController();
    final reviewDay = DateTime.now();
    try {
      var prompt = '今天学了什么、哪里还不明白？有没有花时间特别久的地方？想到什么就用自己的话说出来。';
      var expectedVersion = 0;
      try {
        final invitation = await ref
            .read(apiProvider)
            .selfReviewPrompt(widget.wardId, reviewDay);
        prompt = invitation['prompt'] as String? ?? prompt;
      } catch (_) {
        // The Ward can always write a summary when supporting evidence is unavailable.
      }
      try {
        final current =
            await ref.read(apiProvider).selfReview(widget.wardId, reviewDay);
        expressionController.text = current['raw_expression'] as String? ?? '';
        expectedVersion = current['version'] as int? ?? 0;
      } catch (_) {
        // A first review has no saved expression yet.
      }
      if (!mounted) return;
      final expression = await showDialog<String>(
          context: context,
          builder: (dialogContext) => StatefulBuilder(
              builder: (dialogContext, updateDialog) => AlertDialog(
                      title: const Text('说说今天的学习'),
                      content: SizedBox(
                          width: 460,
                          child: SingleChildScrollView(
                              child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                Text(prompt),
                                const SizedBox(height: 12),
                                TextField(
                                    controller: expressionController,
                                    maxLines: 5,
                                    maxLength: 4000,
                                    onChanged: (_) => updateDialog(() {}),
                                    decoration: const InputDecoration(
                                        hintText: '用自己的话记录今天的想法',
                                        border: OutlineInputBorder())),
                                VoiceComposer(
                                    baseUrl: apiBaseUrl,
                                    tokens: ref.read(tokenStorageProvider),
                                    telemetry: ref.read(telemetryProvider),
                                    voiceFactory: widget.voiceFactory,
                                    holdToTalkText: '按住说总结',
                                    showImageAction: false,
                                    onBeforeRecording: () => ref
                                        .read(apiProvider)
                                        .ensureValidAccess(),
                                    onPickImage: () async {},
                                    onVoiceFinal: (text) async {
                                      expressionController.text =
                                          '${expressionController.text.trim()} $text'
                                              .trim();
                                      updateDialog(() {});
                                    }),
                              ]))),
                      actions: [
                        TextButton(
                            onPressed: () => Navigator.pop(dialogContext),
                            child: const Text('稍后再说')),
                        FilledButton(
                            onPressed: expressionController.text.trim().isEmpty
                                ? null
                                : () => Navigator.pop(dialogContext,
                                    expressionController.text.trim()),
                            child: const Text('整理我的总结')),
                      ])));
      if (expression == null || !mounted) return;
      final draft = await ref
          .read(apiProvider)
          .draftSelfReview(widget.wardId, reviewDay, expression);
      if (!mounted) return;
      final rows = (draft['aspects'] as List? ?? const [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .toList();
      const aspectLabels = {
        'understanding': '理解与疑问',
        'strategy': '试过的方法',
        'time_help': '用时与求助',
        'affect': '感受与信心',
        'context': '学习情境',
        'next_intent': '下次想怎么做',
      };
      final edits = [
        for (final row in rows)
          TextEditingController(text: row['statement'] as String? ?? '')
      ];
      final confirmed = await showDialog<List<Map<String, dynamic>>>(
          context: context,
          builder: (dialogContext) => StatefulBuilder(
              builder: (dialogContext, updateDialog) => AlertDialog(
                    title: const Text('确认你的总结'),
                    content: SizedBox(
                        width: 460,
                        child: SingleChildScrollView(
                            child: Column(
                                mainAxisSize: MainAxisSize.min,
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                              Text(expression),
                              const SizedBox(height: 14),
                              if (rows.isEmpty)
                                const Text('暂时没有整理出条目。仍可以保存你的原话。'),
                              for (var i = 0; i < rows.length; i++)
                                Card(
                                    child: Padding(
                                        padding: const EdgeInsets.all(8),
                                        child: Column(
                                            crossAxisAlignment:
                                                CrossAxisAlignment.start,
                                            children: [
                                              Row(children: [
                                                Expanded(
                                                    child: Text(aspectLabels[
                                                            rows[i][
                                                                'dimension']] ??
                                                        '学习想法')),
                                                IconButton(
                                                    tooltip: '删除这条整理',
                                                    onPressed: () =>
                                                        updateDialog(() {
                                                          rows.removeAt(i);
                                                          edits
                                                              .removeAt(i)
                                                              .dispose();
                                                        }),
                                                    icon:
                                                        const Icon(Icons.close))
                                              ]),
                                              Text(
                                                  '原话：${rows[i]['source_quote']}'),
                                              TextField(
                                                  controller: edits[i],
                                                  maxLength: 300,
                                                  onChanged: (_) =>
                                                      updateDialog(() {}),
                                                  decoration:
                                                      const InputDecoration(
                                                          labelText:
                                                              '你可以修改这条整理'))
                                            ])))
                            ]))),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(dialogContext),
                          child: const Text('返回')),
                      FilledButton(
                          onPressed:
                              edits.any((item) => item.text.trim().isEmpty)
                                  ? null
                                  : () => Navigator.pop(dialogContext, [
                                        for (var i = 0; i < rows.length; i++)
                                          {
                                            ...rows[i],
                                            'statement': edits[i].text.trim()
                                          }
                                      ]),
                          child: const Text('确认并保存'))
                    ],
                  )));
      for (final edit in edits) {
        edit.dispose();
      }
      if (confirmed == null || !mounted) return;
      await ref.read(apiProvider).confirmSelfReview(
          widget.wardId, reviewDay, expression, confirmed, expectedVersion);
      await _refreshCue();
      insight = await ref.read(apiProvider).insight(widget.wardId, reviewDay);
      if (mounted) setState(() => tab = 2);
    } catch (e) {
      if (mounted) showMessage(context, '提交自我总结失败：${userErrorMessage(e)}');
    } finally {
      expressionController.dispose();
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
      if (mounted) showMessage(context, '操作未完成：${userErrorMessage(error)}');
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
    try {
      final result =
          await ref.read(apiProvider).pauseSession(sessionId, seconds);
      if (!mounted) return;
      _clearTrackedSession(sessionId);
      _patchTaskSession(taskId, result);
      await _load();
    } catch (error) {
      if (mounted) showMessage(context, '操作未完成：${userErrorMessage(error)}');
    }
  }

  Future<void> _resumeSession(
      String taskId, String sessionId, int seconds) async {
    try {
      final result = await ref.read(apiProvider).resumeSession(sessionId);
      if (!mounted) return;
      _patchTaskSession(taskId, result);
      _trackSession(sessionId, (result['active_seconds'] as int?) ?? seconds);
      await _load();
    } catch (error) {
      if (mounted) showMessage(context, '操作未完成：${userErrorMessage(error)}');
    }
  }

  Future<void> _finishSession(String taskId, String sessionId, int seconds,
      {String? taskTitle}) async {
    try {
      await ref.read(apiProvider).finishSession(sessionId, seconds);
      if (!mounted) return;
      _clearTrackedSession(sessionId);
      _patchTaskSession(taskId, null);
      showMessage(context, '已记录你声明这项作业完成。');
      await _load();
    } catch (error) {
      if (mounted) showMessage(context, '操作未完成：${userErrorMessage(error)}');
    }
  }

  Future<PickedChatImage?> _defaultPickChatImage() async {
    final image = await ImagePicker().pickImage(
      source: defaultChatImageSource,
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
    if (clearingHistory) return;
    if (sprintSetupOpen) setState(_discardSprintSetup);
    final generation = _chatGeneration;
    if (stagedImages.length >= 8) {
      showMessage(context, '一次最多添加 8 张图片');
      return;
    }
    final image = await (widget.pickChatImage ?? _defaultPickChatImage)();
    if (image == null ||
        !mounted ||
        generation != _chatGeneration ||
        clearingHistory) {
      return;
    }
    if (!const {'jpg', 'jpeg', 'png', 'webp'}.contains(image.extension)) {
      showMessage(context, '暂只支持 JPG、PNG 或 WebP 图片');
      return;
    }
    _openPlanChat();
    final staged = _StagedImage(bytes: image.bytes, extension: image.extension);
    setState(() => stagedImages.add(staged));
    try {
      final key = await ref
          .read(apiProvider)
          .uploadCompanionAttachment(image.bytes, image.extension);
      if (!mounted || !stagedImages.contains(staged)) return;
      setState(() {
        staged.key = key;
        _cacheChatImage(key, staged.bytes);
      });
    } catch (_) {
      if (!mounted || !stagedImages.contains(staged)) return;
      setState(() => staged.failed = true);
      showMessage(context, '图片上传失败，请重试');
    }
  }

  Future<void> _submitPlanInput(String text,
      {bool pronunciation = false}) async {
    if (_chatBusy) return;
    planAttachments
      ..clear()
      ..addAll([
        for (final image in stagedImages)
          if (image.key != null) image.key!,
      ]);
    final generation = _chatGeneration;
    setState(() {
      planSending = true;
    });
    try {
      final result = await ref.read(apiProvider).companionTurn(
          content: text,
          threadId: companionThreadId,
          expectedThreadVersion: companionThreadVersion,
          attachmentKeys: List<String>.from(planAttachments),
          routeHint: pronunciation ? 'tutoring' : null,
          tutoringIntent: pronunciation ? 'pronunciation' : null);
      if (!mounted || generation != _chatGeneration) return;
      await _applyPlanTurnResult(result);
    } catch (_) {
      if (!mounted || generation != _chatGeneration) return;
      if (mounted && generation == _chatGeneration) {
        setState(() => failedPlanText = text);
        showMessage(context, '暂时无法整理今天的计划，请重试');
      }
    } finally {
      if (mounted && generation == _chatGeneration) {
        setState(() => planSending = false);
      }
    }
  }

  Future<void> _chooseIntent(
      _ChatLine message, Map<String, dynamic> action) async {
    if (_chatBusy ||
        message.threadId != companionThreadId ||
        message.threadVersion != companionThreadVersion) {
      return;
    }
    final generation = _chatGeneration;
    setState(() => planSending = true);
    try {
      final result = await ref.read(apiProvider).companionTurn(
        content: '选择：${action['label']}',
        threadId: companionThreadId,
        expectedThreadVersion: companionThreadVersion,
        structuredCommand: {
          'interaction_id': action['id'],
          'command': 'choose_intent',
          'payload': action['payload'],
        },
      );
      if (!mounted || generation != _chatGeneration) return;
      await _applyPlanTurnResult(result);
    } on DioException catch (error) {
      if (!mounted || generation != _chatGeneration) return;
      if (error.response?.statusCode == 409) {
        try {
          if (!mounted || generation != _chatGeneration) return;
          await _refreshTranscript();
        } catch (_) {
          if (!mounted || generation != _chatGeneration) return;
        }
        if (mounted && generation == _chatGeneration) {
          showMessage(context, '这个选择已过期，请重新说明。');
        }
      } else if (mounted && generation == _chatGeneration) {
        showMessage(context, '选择没有送达，请重试');
      }
    } catch (_) {
      if (!mounted || generation != _chatGeneration) return;
      if (mounted && generation == _chatGeneration) {
        showMessage(context, '选择没有送达，请重试');
      }
    } finally {
      if (mounted && generation == _chatGeneration) {
        setState(() => planSending = false);
      }
    }
  }

  Future<void> _applyPlanTurnResult(Map<String, dynamic> result) async {
    final generation = _chatGeneration;
    final interaction =
        Map<String, dynamic>.from(result['interaction'] as Map? ?? const {});
    companionThreadId = result['thread_id'] as String?;
    companionThreadVersion = result['thread_version'] as int?;
    if (companionThreadId != null && companionThreadVersion != null) {
      await ref
          .read(tokenStorageProvider)
          .saveCompanionThread(companionThreadId!, companionThreadVersion!);
    }
    if (!mounted || generation != _chatGeneration) return;
    final objectRef = Map<String, dynamic>.from(
        interaction['object_ref'] as Map? ?? const {});
    final actions = (interaction['actions'] as List? ?? const [])
        .map((action) => Map<String, dynamic>.from(action as Map));
    Map<String, dynamic>? draft;
    Map<String, dynamic>? lesson;
    if (objectRef['context'] == 'planning' &&
        objectRef['object_id'] is String) {
      draft = await ref
          .read(apiProvider)
          .companionPlanDraft(objectRef['object_id'] as String);
    }
    if (interaction['kind'] == 'pronunciation_lesson' &&
        objectRef['object_id'] is String) {
      lesson = await ref
          .read(apiProvider)
          .pronunciationLesson(objectRef['object_id'] as String);
    }
    if (!mounted || generation != _chatGeneration) return;
    final nextDraftId = draft?['draft_id'] as String?;
    final nextDraftVersion = draft?['object_version'] as int?;
    setState(() {
      failedPlanText = null;
      stagedImages.clear();
      planAttachments.clear();
      final rawLessons = lesson?['lessons'] ?? interaction['lessons'];
      pronunciationLessons = rawLessons is List && rawLessons.isNotEmpty
          ? [
              for (final item in rawLessons)
                if (item is Map) Map<String, dynamic>.from(item),
            ]
          : (lesson != null ? [lesson] : const []);
      planFeedback = ((interaction['parts'] as List? ?? const []).isNotEmpty)
          ? Map<String, dynamic>.from(
              (interaction['parts'] as List).first as Map)['text'] as String?
          : null;
      planConfirmAction = null;
      sprintAction = null;
      planSuggestionAction = null;
      planClarifyAction = null;
      for (final action in actions) {
        if (action['command'] == 'sprint_command' &&
            action['enabled'] == true) {
          sprintAction = action;
        }
        if (action['command'] == 'confirm_plan' && action['enabled'] == true) {
          planConfirmAction = action;
        }
        if (action['command'] == 'accept_plan_suggestion' &&
            action['enabled'] == true) {
          planSuggestionAction = action;
        }
        if (action['command'] == 'clarify_reply' && action['enabled'] == true) {
          planClarifyAction = action;
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
      planAdviceItems = planInteractionKind == 'clarify'
          ? (draft?['items'] as List? ?? const [])
              .map((item) => Map<String, dynamic>.from(item as Map))
              .toList()
          : [];
      if (planDraftId != nextDraftId || planDraftVersion != nextDraftVersion) {
        dismissedPlanSuggestions.clear();
      }
      planDraftId = nextDraftId;
      planDraftVersion = nextDraftVersion;
      final batch = Map<String, dynamic>.from(
          draft?['clarification_batch'] as Map? ?? const {});
      planClarificationSlots = planInteractionKind == 'clarify'
          ? (batch['slots'] as List? ?? const [])
              .map((slot) => Map<String, dynamic>.from(slot as Map))
              .toList()
          : [];
    });
    // RegisterTask happens inside the Planning workflow.  Reload the home
    // projections immediately so an unscheduled task is visible in its
    // actual task-pool home, not only in this transient chat card.
    await _load();
    if (!mounted || generation != _chatGeneration) return;
    await _refreshTranscript();
  }

  String? _suggestedClock(dynamic value) {
    final parsed = DateTime.tryParse(value?.toString() ?? '');
    if (parsed == null) return null;
    final shanghai = parsed.toUtc().add(const Duration(hours: 8));
    return '${shanghai.hour.toString().padLeft(2, '0')}:${shanghai.minute.toString().padLeft(2, '0')}';
  }

  Widget _planSuggestion(Map<String, dynamic> target, String kind,
      {bool showActions = true, bool honorDismissal = true}) {
    final raw =
        target[kind == 'time' ? 'time_suggestion' : 'duration_suggestion'];
    if (raw is! Map) return const SizedBox.shrink();
    final suggestion = Map<String, dynamic>.from(raw);
    final targetId = (target['assignment_id'] ?? target['slot_id'])?.toString();
    if (targetId == null) return const SizedBox.shrink();
    final key = '$kind:$targetId';
    if (honorDismissal && dismissedPlanSuggestions.contains(key)) {
      return const SizedBox.shrink();
    }
    final minutes = suggestion['suggested_minutes'];
    final start = _suggestedClock(suggestion['suggested_start_at']);
    final end = _suggestedClock(suggestion['suggested_end_at']);
    final text = kind == 'time'
        ? '${suggestion['reason']} ${start == null ? '目前没有不冲突的调整时间。' : '可改为 $start–$end。'}建议时段为 07:00–22:00。'
        : '${target['title']}：近 15 天 ${suggestion['sample_count']} 次同名任务，实际用时中位数约 ${suggestion['actual_median_minutes']} 分钟，建议预计 $minutes 分钟。';
    final canAccept =
        (kind == 'clarification' ? planClarifyAction : planSuggestionAction) !=
                null &&
            (kind != 'time' || start != null);
    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(text, style: const TextStyle(fontSize: 12)),
        if (showActions)
          Row(children: [
            if (canAccept)
              TextButton(
                key: Key('accept-plan-suggestion-$key'),
                onPressed: _chatBusy
                    ? null
                    : () => _acceptPlanSuggestion(target, kind),
                child: const Text('采用建议'),
              ),
            TextButton(
              key: Key('dismiss-plan-suggestion-$key'),
              onPressed: () =>
                  setState(() => dismissedPlanSuggestions.add(key)),
              child: const Text('先不改'),
            ),
          ]),
      ]),
    );
  }

  Future<void> _acceptPlanSuggestion(
      Map<String, dynamic> target, String kind) async {
    if (_chatBusy || planDraftId == null || planDraftVersion == null) return;
    final action =
        kind == 'clarification' ? planClarifyAction : planSuggestionAction;
    if (action == null) return;
    final payload = kind == 'clarification'
        ? {
            'draft_id': planDraftId,
            'answers': [
              {
                'slot_id': target['slot_id'],
                'value':
                    '${(target['duration_suggestion'] as Map)['suggested_minutes']}分钟'
              },
            ],
          }
        : {
            'draft_id': planDraftId,
            'expected_draft_version': planDraftVersion,
            'kind': kind,
            'task_id': target['assignment_id'],
            'expected_fingerprint':
                (target['${kind}_suggestion'] as Map)['fingerprint'],
          };
    final generation = _chatGeneration;
    setState(() => planSending = true);
    try {
      final result = await ref.read(apiProvider).companionTurn(
        content: '采用建议',
        threadId: companionThreadId,
        expectedThreadVersion: companionThreadVersion,
        structuredCommand: {
          'interaction_id': action['id'],
          'command': action['command'],
          'payload': payload,
        },
      );
      if (!mounted || generation != _chatGeneration) return;
      await _applyPlanTurnResult(result);
    } on DioException catch (error) {
      if (!mounted || generation != _chatGeneration) return;
      if (error.response?.statusCode == 409) {
        if (mounted && generation == _chatGeneration) {
          setState(() {
            planDraft = [];
            planAdviceItems = [];
            planClarificationSlots = [];
            planSuggestionAction = null;
            planClarifyAction = null;
          });
        }
        await _load();
        if (!mounted || generation != _chatGeneration) return;
        await _refreshTranscript(restoreReviewAction: false);
        if (mounted && generation == _chatGeneration) {
          showMessage(context, '计划已变化，请重新说明或审阅。');
        }
      } else if (mounted && generation == _chatGeneration) {
        showMessage(context, '采用建议失败，请稍后重试');
      }
    } catch (_) {
      if (!mounted || generation != _chatGeneration) return;
      if (mounted && generation == _chatGeneration) {
        showMessage(context, '采用建议失败，请稍后重试');
      }
    } finally {
      if (mounted && generation == _chatGeneration) {
        setState(() => planSending = false);
      }
    }
  }

  Future<void> _confirmPlanDraft() async {
    if (planDraft.isEmpty ||
        _chatBusy ||
        planConfirmAction == null ||
        planDraftId == null ||
        planDraftVersion == null) {
      return;
    }
    final generation = _chatGeneration;
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
      if (!mounted || generation != _chatGeneration) return;
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
      if (!mounted || generation != _chatGeneration) return;
      planAttachments.clear();
      planDraft = [];
      planAdviceItems = [];
      planFeedback = null;
      planInteractionKind = null;
      planConfirmAction = null;
      planSuggestionAction = null;
      planClarifyAction = null;
      planClarificationSlots = [];
      dismissedPlanSuggestions.clear();
      planDraftId = null;
      planDraftVersion = null;
      await _load();
      if (!mounted || generation != _chatGeneration) return;
      await _refreshTranscript();
      if (mounted && generation == _chatGeneration) {
        showMessage(context, '今天计划已确认');
      }
    } on DioException catch (error) {
      if (!mounted || generation != _chatGeneration) return;
      if (error.response?.statusCode == 409) {
        if (mounted && generation == _chatGeneration) {
          setState(() {
            planDraft = [];
            planAdviceItems = [];
            planConfirmAction = null;
            planSuggestionAction = null;
            planClarifyAction = null;
            planClarificationSlots = [];
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
          if (!mounted || generation != _chatGeneration) return;
          await _refreshTranscript(restoreReviewAction: false);
        } catch (_) {
          if (!mounted || generation != _chatGeneration) return;
        }
        if (mounted && generation == _chatGeneration) {
          showMessage(context, '计划已变化，已刷新，请重新说明或确认。');
        }
      } else if (mounted && generation == _chatGeneration) {
        showMessage(context, '确认计划失败，请稍后重试');
      }
    } catch (_) {
      if (!mounted || generation != _chatGeneration) return;
      if (mounted && generation == _chatGeneration) {
        showMessage(context, '确认计划失败，请稍后重试');
      }
    } finally {
      if (mounted && generation == _chatGeneration) {
        setState(() => planSending = false);
      }
    }
  }

  _ChatLine _parseChatLine(Object? raw) {
    final item = Map<String, dynamic>.from(raw as Map);
    final refs =
        (item['attachment_refs'] as List? ?? const []).whereType<String>();
    final interactionRef = item['interaction_ref'] is Map
        ? Map<String, dynamic>.from(item['interaction_ref'] as Map)
        : null;
    final id = item['id'] as String? ??
        (item['thread_id'] != null && item['thread_version'] != null
            ? '${item['thread_id']}:${item['thread_version']}'
            : null);
    return _ChatLine(
        id: id,
        threadId: item['thread_id'] as String?,
        threadVersion: item['thread_version'] as int?,
        label: item['author_type'] == 'ward' ? '我' : '读学 AI',
        content: item['content'] as String,
        imageRefs: refs.toList(),
        images: [
          for (final ref in refs)
            if (rememberedImages[ref] != null) rememberedImages[ref]!,
        ],
        visual: interactionRef == null
            ? null
            : visualFromInteraction(interactionRef),
        lessons: _lessonsFromInteraction(interactionRef),
        interactionRef: interactionRef,
        intentActions: interactionRef?['kind'] == 'intent_choice'
            ? [
                for (final action
                    in (interactionRef?['actions'] as List? ?? const []))
                  if (action is Map && action['command'] == 'choose_intent')
                    Map<String, dynamic>.from(action),
              ]
            : const []);
  }

  bool get _messagesCarryPronunciation =>
      historyMessages.any((message) => message.lessons.isNotEmpty) ||
      planMessages.any((message) => message.lessons.isNotEmpty);

  bool get _currentMessageCarriesPlanReview =>
      [...historyMessages, ...planMessages].any((message) =>
          message.threadId == companionThreadId &&
          message.threadVersion == companionThreadVersion &&
          message.planReview != null);

  void _anchorPlanReview() {
    if (planInteractionKind != 'plan_confirm_list' ||
        planDraft.isEmpty ||
        _currentMessageCarriesPlanReview) {
      return;
    }
    for (final lines in [planMessages, historyMessages]) {
      for (var index = lines.length - 1; index >= 0; index--) {
        if (lines[index].label == '我') {
          continue;
        }
        lines[index] = lines[index].copyWith(interactionRef: {
          'kind': 'plan_confirm_list',
          'card_snapshot': {'items': planDraft},
        });
        return;
      }
    }
  }

  void _anchorPronunciationLessons() {
    if (pronunciationLessons.isEmpty) return;
    final lessons = pronunciationLessons;
    pronunciationLessons = const [];
    for (final lines in [planMessages, historyMessages]) {
      for (var index = lines.length - 1; index >= 0; index--) {
        if (lines[index].label == '我') {
          continue;
        }
        lines[index] = lines[index].copyWith(lessons: lessons);
        return;
      }
    }
    planMessages.add(_ChatLine(label: '读学 AI', content: '', lessons: lessons));
  }

  Widget _pronunciationCard(Map<String, dynamic> lesson) =>
      PronunciationLessonCard(
        key: ValueKey(lesson['speech_ref'] ?? lesson['source_text']),
        lesson: lesson,
        loadSpeech: (speechRef, rate) =>
            ref.read(apiProvider).pronunciationSpeech(speechRef, rate),
        playback: _playback(),
      );

  Widget _chatMessage(_ChatLine message) => Padding(
        padding: const EdgeInsets.only(top: 10),
        child: Column(
          crossAxisAlignment: message.label == '我'
              ? CrossAxisAlignment.end
              : CrossAxisAlignment.start,
          children: [
            _ChatBubble(
                key: message.id != null ? ValueKey('msg-${message.id}') : null,
                label: message.label,
                text: message.content,
                images: message.images,
                imageCount: message.imageRefs.length,
                loadImage: message.imageRefs.isEmpty
                    ? null
                    : (index) => _loadChatImage(message, index),
                visual: message.visual),
            if (message.intentActions.isNotEmpty &&
                message.threadId == companionThreadId &&
                message.threadVersion == companionThreadVersion)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Wrap(spacing: 8, runSpacing: 8, children: [
                  for (final action in message.intentActions)
                    OutlinedButton(
                      key: ValueKey(
                          'intent-choice-${(action['payload'] as Map)['intent']}'),
                      onPressed: _chatBusy || action['enabled'] != true
                          ? null
                          : () => _chooseIntent(message, action),
                      child: Text(action['label'] as String),
                    ),
                ]),
              ),
            for (final lesson in message.lessons)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: _pronunciationCard(lesson),
              ),
            if (message.planReview != null)
              _planReviewCard(message.planReview!,
                  active: message.threadId == companionThreadId &&
                      message.threadVersion == companionThreadVersion &&
                      planConfirmAction != null &&
                      planDraft.isNotEmpty),
          ],
        ),
      );

  Future<Uint8List> _loadChatImage(_ChatLine message, int index) {
    final generation = _chatGeneration;
    final key = message.imageRefs[index];
    final cached = rememberedImages[key];
    if (cached != null) return Future.value(cached);
    return _imageLoads.putIfAbsent(key, () async {
      try {
        final bytes = await ref
            .read(apiProvider)
            .companionMessageImage(message.id!, index);
        if (generation == _chatGeneration) _cacheChatImage(key, bytes);
        return bytes;
      } finally {
        _imageLoads.remove(key);
      }
    });
  }

  void _cacheChatImage(String key, Uint8List bytes) {
    rememberedImages.remove(key);
    rememberedImages[key] = bytes;
    while (rememberedImages.length > 48) {
      rememberedImages.remove(rememberedImages.keys.first);
    }
  }

  void _scrollToChatBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_chatScrollController.hasClients) return;
      final position = _chatScrollController.position;
      if (position.maxScrollExtent > 0) {
        _chatScrollController.jumpTo(position.maxScrollExtent);
      }
    });
  }

  // Only auto-load on scroll after the user has scrolled away from the top
  // and then scrolls back up near the top; prevents auto-fetching every page
  // immediately when the list first renders at pixels == 0.
  bool _userScrolledAwayFromTop = false;
  void _onChatScroll() {
    if (!planChatOpen ||
        loadingOlderMessages ||
        !_hasOlderHistory ||
        !_chatScrollController.hasClients) {
      return;
    }
    final position = _chatScrollController.position;
    if (position.pixels > 80) {
      _userScrolledAwayFromTop = true;
    } else if (_userScrolledAwayFromTop &&
        position.pixels <= 32 &&
        position.maxScrollExtent > 0) {
      _userScrolledAwayFromTop = false;
      _loadOlderMessages();
    }
  }

  Future<void> _loadOlderMessages() async {
    if (clearingHistory || loadingOlderMessages || !_hasOlderHistory) return;
    final generation = _chatGeneration;
    final targetThreadId = nextBeforeThreadVersion != null
        ? (historyCursorThreadId ?? companionThreadId)
        : previousThreadId;
    final beforeVersion = nextBeforeThreadVersion;
    if (targetThreadId == null) return;

    final hadClients = _chatScrollController.hasClients;
    final oldMaxExtent =
        hadClients ? _chatScrollController.position.maxScrollExtent : 0.0;
    final oldPixels = hadClients ? _chatScrollController.position.pixels : 0.0;

    setState(() => loadingOlderMessages = true);
    try {
      final page = await ref.read(apiProvider).companionMessages(
            targetThreadId,
            beforeThreadVersion: beforeVersion,
          );
      if (!mounted || generation != _chatGeneration) return;
      final rawMessages = page['messages'] as List? ?? const [];
      final olderLines = rawMessages.map(_parseChatLine).toList();
      final existingIds = <String>{
        for (final m in historyMessages)
          if (m.id != null) m.id!,
        for (final m in planMessages)
          if (m.id != null) m.id!,
      };
      final deduped = [
        for (final line in olderLines)
          if (line.id == null || !existingIds.contains(line.id)) line,
      ];
      setState(() {
        historyMessages.insertAll(0, deduped);
        historyCursorThreadId = targetThreadId;
        nextBeforeThreadVersion = page['next_before_thread_version'] as int?;
        previousThreadId = page['previous_thread_id'] as String?;
      });
      if (hadClients && deduped.isNotEmpty) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!mounted ||
              generation != _chatGeneration ||
              !_chatScrollController.hasClients) {
            return;
          }
          final newMaxExtent = _chatScrollController.position.maxScrollExtent;
          final delta = newMaxExtent - oldMaxExtent;
          if (delta > 0) {
            _chatScrollController.jumpTo(oldPixels + delta);
          }
        });
      }
    } catch (_) {
      // Ignore transient network errors when paginating history.
    } finally {
      if (mounted && generation == _chatGeneration) {
        setState(() => loadingOlderMessages = false);
      }
    }
  }

  Future<void> _refreshTranscript({bool restoreReviewAction = true}) async {
    final generation = _chatGeneration;
    final Map<String, dynamic> transcript;
    if (companionThreadId != null) {
      transcript =
          await ref.read(apiProvider).companionMessages(companionThreadId!);
    } else {
      transcript = await ref.read(apiProvider).currentCompanionMessages();
    }
    final resolvedThreadId =
        (transcript['thread_id'] as String?) ?? companionThreadId;
    final version = transcript['thread_version'] as int?;
    final messages = transcript['messages'] as List? ?? const [];
    if (!mounted || generation != _chatGeneration) return;
    final latestLines = messages.map(_parseChatLine).toList();
    final latestIds = <String>{
      for (final m in latestLines)
        if (m.id != null) m.id!,
    };
    setState(() {
      if (resolvedThreadId != null) {
        companionThreadId = resolvedThreadId;
      }
      companionThreadVersion = version;
      if (historyMessages.isEmpty) {
        historyCursorThreadId = resolvedThreadId;
        nextBeforeThreadVersion =
            transcript['next_before_thread_version'] as int?;
        previousThreadId = transcript['previous_thread_id'] as String?;
      } else {
        historyMessages
            .removeWhere((m) => m.id != null && latestIds.contains(m.id));
      }
      planMessages
        ..clear()
        ..addAll(latestLines);
      final latestReview =
          latestLines.isNotEmpty && latestLines.last.threadVersion == version
              ? latestLines.last
              : null;
      final reviewRef = latestReview?.interactionRef;
      if (restoreReviewAction &&
          latestReview?.planReview != null &&
          reviewRef != null) {
        final action = (reviewRef['actions'] as List? ?? const [])
            .whereType<Map>()
            .map((value) => Map<String, dynamic>.from(value))
            .where((value) =>
                value['command'] == 'confirm_plan' && value['enabled'] == true);
        final objectRef = reviewRef['object_ref'] is Map
            ? Map<String, dynamic>.from(reviewRef['object_ref'] as Map)
            : const <String, dynamic>{};
        if (action.isNotEmpty &&
            objectRef['object_id'] is String &&
            objectRef['object_version'] is int) {
          planInteractionKind = 'plan_confirm_list';
          planConfirmAction = action.first;
          planDraft = latestReview!.planReview!;
          planDraftId = objectRef['object_id'] as String;
          planDraftVersion = objectRef['object_version'] as int;
        }
      }
      if (latestLines.any((message) => message.lessons.isNotEmpty)) {
        pronunciationLessons = const [];
      }
    });
    if (version != null && companionThreadId != null) {
      await ref
          .read(tokenStorageProvider)
          .saveCompanionThread(companionThreadId!, version);
    }
  }

  Future<void> _restoreCompanionThread() async {
    final generation = _chatGeneration;
    final tokens = ref.read(tokenStorageProvider);
    final threadId = await tokens.companionThreadId;
    final version = await tokens.companionThreadVersion;
    if (!mounted || generation != _chatGeneration) return;
    if (threadId != null && version != null) {
      companionThreadId = threadId;
      companionThreadVersion = version;
    }
    try {
      await _refreshTranscript();
    } on DioException catch (error) {
      if (error.response?.statusCode == 404 &&
          mounted &&
          generation == _chatGeneration) {
        companionThreadId = null;
        companionThreadVersion = null;
        try {
          await _refreshTranscript();
        } catch (_) {}
      }
    } catch (_) {
      // Keep local companionThreadId on transient errors so history is not lost.
    }
  }
}

class _HomeOverlay extends StatelessWidget {
  const _HomeOverlay({
    required this.title,
    required this.subtitle,
    required this.onClose,
    required this.child,
    this.bottomInset = 82,
    this.action,
    this.banner,
    this.closeTooltip = '关闭',
  });
  final String closeTooltip;
  final String title;
  final String subtitle;
  final VoidCallback? onClose;
  final Widget child;
  final double bottomInset;
  final Widget? action;
  final Widget? banner;

  @override
  Widget build(BuildContext context) => Positioned.fill(
      child: ColoredBox(
          color: Theme.of(context).scaffoldBackgroundColor,
          child: SafeArea(
              child: Padding(
                  padding: EdgeInsets.only(bottom: bottomInset),
                  child: Material(
                      color: Theme.of(context).scaffoldBackgroundColor,
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
                                  if (action != null) action!,
                                  if (onClose != null)
                                    IconButton(
                                        onPressed: onClose,
                                        tooltip: closeTooltip,
                                        icon: const Icon(Icons.close)),
                                ])),
                        if (banner != null) banner!,
                        const Divider(height: 1),
                        Expanded(child: child),
                      ]))))));
}

class _ChatLine {
  const _ChatLine({
    this.id,
    this.threadId,
    this.threadVersion,
    required this.label,
    required this.content,
    this.images = const [],
    this.imageRefs = const [],
    this.visual,
    this.lessons = const [],
    this.intentActions = const [],
    this.interactionRef,
  });
  final String? id;
  final String? threadId;
  final int? threadVersion;
  final String label;
  final String content;
  final List<Uint8List> images;
  final List<String> imageRefs;
  final Map<String, dynamic>? visual;
  final List<Map<String, dynamic>> lessons;
  final List<Map<String, dynamic>> intentActions;
  final Map<String, dynamic>? interactionRef;

  List<Map<String, dynamic>>? get planReview {
    if (interactionRef?['kind'] != 'plan_confirm_list') return null;
    final snapshot = interactionRef?['card_snapshot'];
    if (snapshot is! Map || snapshot['items'] is! List) return null;
    return [
      for (final item in snapshot['items'] as List)
        if (item is Map) Map<String, dynamic>.from(item),
    ];
  }

  _ChatLine copyWith(
          {List<Map<String, dynamic>>? lessons,
          Map<String, dynamic>? interactionRef}) =>
      _ChatLine(
        id: id,
        threadId: threadId,
        threadVersion: threadVersion,
        label: label,
        content: content,
        images: images,
        imageRefs: imageRefs,
        visual: visual,
        lessons: lessons ?? this.lessons,
        intentActions: intentActions,
        interactionRef: interactionRef ?? this.interactionRef,
      );
}

List<Map<String, dynamic>> _lessonsFromInteraction(
    Map<String, dynamic>? interaction) {
  if (interaction == null || interaction['kind'] != 'pronunciation_lesson') {
    return const [];
  }
  final raw = interaction['lessons'];
  if (raw is! List) return const [];
  return [
    for (final item in raw)
      if (item is Map) Map<String, dynamic>.from(item),
  ];
}

class _ChatBubble extends StatelessWidget {
  const _ChatBubble({
    super.key,
    required this.label,
    required this.text,
    this.images = const [],
    this.imageCount = 0,
    this.loadImage,
    this.visual,
  });
  final String label;
  final String text;
  final List<Uint8List> images;
  final int imageCount;
  final Future<Uint8List> Function(int index)? loadImage;
  final Map<String, dynamic>? visual;

  @override
  Widget build(BuildContext context) {
    final isWard = label == '我';
    final count = imageCount > 0 ? imageCount : images.length;
    Future<Uint8List> imageAt(int index) =>
        loadImage?.call(index) ?? Future.value(images[index]);
    return LayoutBuilder(builder: (context, constraints) {
      final maxWidth =
          isWard ? constraints.maxWidth * 2 / 3 : constraints.maxWidth;
      return Align(
          alignment: isWard ? Alignment.centerRight : Alignment.centerLeft,
          child: Container(
              key: ValueKey('chat-bubble-${isWard ? 'ward' : 'ai'}-$text'),
              constraints: BoxConstraints(maxWidth: maxWidth),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                  color: isWard
                      ? const Color(0xffdbeafe)
                      : const Color(0xfff8fafc),
                  border: Border.all(
                      color: isWard
                          ? const Color(0xff93c5fd)
                          : const Color(0xffe2e8f0)),
                  borderRadius: BorderRadius.circular(16)),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (!isWard)
                      Text(label,
                          style: const TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w700,
                              color: Colors.blueGrey)),
                    if (count > 0) ...[
                      const SizedBox(height: 6),
                      Wrap(spacing: 6, runSpacing: 6, children: [
                        for (var index = 0; index < count; index++)
                          GestureDetector(
                            onTap: () => Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) => ChatImageViewer(
                                  imageCount: count,
                                  initialIndex: index,
                                  loadImage: imageAt,
                                ),
                              ),
                            ),
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(8),
                              child: FutureBuilder<Uint8List>(
                                future: imageAt(index),
                                builder: (context, snapshot) => snapshot.hasData
                                    ? Image.memory(snapshot.data!,
                                        key: ValueKey('sent-chat-image-$index'),
                                        width: 72,
                                        height: 72,
                                        fit: BoxFit.cover,
                                        cacheWidth: chatImageCachePixels(
                                            72,
                                            MediaQuery.devicePixelRatioOf(
                                                context)),
                                        cacheHeight: chatImageCachePixels(
                                            72,
                                            MediaQuery.devicePixelRatioOf(
                                                context)),
                                        gaplessPlayback: true)
                                    : Container(
                                        key: ValueKey('sent-chat-image-$index'),
                                        width: 72,
                                        height: 72,
                                        color: const Color(0xffe2e8f0),
                                        child: Icon(snapshot.hasError
                                            ? Icons.broken_image_outlined
                                            : Icons.image_outlined)),
                              ),
                            ),
                          ),
                      ]),
                    ],
                    if (text.isNotEmpty &&
                        !(count > 0 && text == '请看这张图片。')) ...[
                      const SizedBox(height: 4),
                      ChatMarkdownBody(text: text),
                    ],
                    if (visual != null) ...[
                      const SizedBox(height: 8),
                      VisualBlock(visual: visual!),
                    ],
                  ])));
    });
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
