import 'dart:async';

import 'dart:math';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollDirection;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import '../core/cue_notifications.dart';
import '../core/cue_refresh_schedule.dart';
import '../core/speech_playback.dart';
import '../core/voice_transcription_service.dart';
import '../core/user_error_message.dart';
import '../providers.dart';
import '../core/conversation_latency.dart';
import '../shared/app_ui.dart';
import '../shared/chat_markdown.dart';
import '../shared/reply_progress.dart';
import '../shared/voice_composer.dart';
import 'conversation_picker.dart';
import 'ward_creative_work.dart';
import 'guardian_report_view.dart';
import 'sprint_card.dart';
import 'chat_image_viewer.dart';
import 'pronunciation_player.dart';
import 'start_cue_card.dart';
import 'visual_block.dart';

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
  Map<String, dynamic>? profile, startCue;
  Map<String, dynamic>? sprint, readySprint, sprintAction;
  Map<String, dynamic>? pendingSprintNotice;
  String? hiddenSprintId;
  bool sprintBusy = false;
  int sprintGeneration = 0;
  bool sprintForeground = true;
  Timer? sprintRefresh;
  late final SprintCountdown sprintCountdown;
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
  List<String> _failedAttachmentKeys = const [];
  final stagedImages = <_StagedImage>[];
  final planMessages = <_ChatLine>[];
  final historyMessages = <_ChatLine>[];
  final rememberedImages = <String, Uint8List>{};
  final _imageLoads = <String, Future<Uint8List>>{};
  final ScrollController _chatScrollController = ScrollController();
  final _chatTailKey = GlobalKey();
  int _chatScrollRevision = 0;
  String? companionThreadId;
  int? companionThreadVersion;
  int? nextBeforeThreadVersion;
  String? historyCursorThreadId;
  bool loadingOlderMessages = false;
  String? failedPlanText, _failedCommandId;
  bool _failedPronunciation = false;
  List<Map<String, dynamic>> pronunciationLessons = const [];
  SpeechPlayback? _speechPlayback;
  String? _voiceDisplayText;
  bool _autoRead = false;
  bool _autoReadChanged = false;
  String? _failedVoiceDisplay;
  int _speechGeneration = 0;
  String? _readingId;
  bool _playbackClaimed = false;
  StreamSubscription<void>? _playbackComplete;

  CancelToken? _speechRequest;
  final _replyAudio = <String, Uint8List>{};

  Stream<List<int>> _cacheReply(Stream<Uint8List> frames, String key, int generation) async* {
    final buffer = BytesBuilder(copy: false);
    const maxBytes = 2 * 1024 * 1024;
    var cacheable = true;
    await for (final frame in frames) {
      if (generation != _speechGeneration) return;
      if (cacheable && buffer.length + frame.length > maxBytes) {
        buffer.clear();
        cacheable = false;
      }
      if (cacheable) buffer.add(frame);
      yield frame;
    }
    if (cacheable && buffer.isNotEmpty && generation == _speechGeneration) {
      if (_replyAudio.length >= 4) _replyAudio.remove(_replyAudio.keys.first);
      _replyAudio[key] = buffer.takeBytes();
    }
  }

  Future<void> _stopSpeech() async {
    _speechRequest?.cancel();
    _speechGeneration++;
    if (mounted && _readingId != null) setState(() => _readingId = null);
    if (_playbackClaimed) {
      _playbackClaimed = false;
      await _speechPlayback?.stop();
    }
  }

  Future<void> _readReply(_ChatLine message) async {
    final latency = Stopwatch()..start();
    _speechRequest?.cancel();
    final stopping = _readingId == message.id;
    final generation = ++_speechGeneration;
    setState(() => _readingId = stopping ? null : message.id);
    final playback = _playback();
    _playbackClaimed = !stopping;
    try {
      await playback.stop();
      if (stopping || !mounted || generation != _speechGeneration) return;
      final key = '${widget.wardId}/${message.id!}';
      final cached = _replyAudio[key];
      if (cached != null) {
        await playback.playMp3(cached);
      } else {
        final cancel = _speechRequest = CancelToken();
        final frames = await ref.read(apiProvider).companionSpeech(message.id!, cancel);
        if (!mounted || generation != _speechGeneration) return;
        await playback.playStream(_cacheReply(frames, key, generation));
      }
      if (mounted && generation == _speechGeneration) {
        ref.read(telemetryProvider).recordMetric(
            'app.tts.playback_latency', latency.elapsedMilliseconds.toDouble());
      }
    } catch (_) {
      if (mounted && generation == _speechGeneration) {
        setState(() => _readingId = null);
        showMessage(context, '暂时无法朗读，请稍后重试');
      }
    }
  }
  bool planSending = false;
  bool _waitingForReply = false;
  List<ReplyStage> _replyStages = const [];
  bool clearingHistory = false;
  bool get _chatBusy => planSending || clearingHistory;

  void Function(String) _startCompanionReply() {
    final generation = _chatGeneration;
    final stages = [ReplyStage.preparing];
    setState(() {
      planSending = true;
      _waitingForReply = true;
      _replyStages = stages;
    });
    return (value) {
      final stage = ReplyStage.fromWire(value);
      if (!mounted ||
          generation != _chatGeneration ||
          !planSending ||
          !_waitingForReply ||
          !identical(stages, _replyStages) ||
          stage == null ||
          stage == stages.last) {
        return;
      }
      _scrollToChatBottom(onlyIfNearBottom: true);
      setState(() => stages.add(stage));
    };
  }

  int _chatGeneration = 0;
  int _quietVersion = 0;
  ConversationTurn? _questionTiming;
  Stopwatch? _photoLatency;
  String? _photoCommandId;

  void _photoVisible(String? commandId) {
    if (!mounted || commandId == null || commandId != _photoCommandId) return;
    final timer = _photoLatency;
    if (timer == null) return;
    _photoLatency = null;
    ref.read(telemetryProvider).recordMetric(
        'app.search_photo.visible_latency', timer.elapsedMilliseconds.toDouble());
  }

  bool chatOpen = false;
  String? chatSubject;
  Timer? timer;
  Timer? cueRefresh;
  @override
  void initState() {
    super.initState();
    ref.read(tokenStorageProvider).autoReadReplies(widget.wardId).then((enabled) {
      if (mounted && !_autoReadChanged && enabled) setState(() => _autoRead = true);
    });
    sprintCountdown = SprintCountdown(onElapsed: _refreshSprint);
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

  SpeechPlayback _playback() {
    if (_speechPlayback != null) return _speechPlayback!;
    final playback = (widget.speechPlayback ?? DeviceSpeechPlayback.new)();
    _playbackComplete = playback.onComplete.listen((_) {
      if (mounted && _readingId != null) setState(() => _readingId = null);
    }, onError: (Object error) {
      if (mounted && _readingId != null) {
        unawaited(_stopSpeech());
        showMessage(context, '暂时无法朗读，请稍后重试');
      }
    });
    return _speechPlayback = playback;
  }

  @override
  void didUpdateWidget(covariant WardDayPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.wardId != widget.wardId) {
      _replyAudio.clear();
      unawaited(_stopSpeech());
    }
  }

  @override
  void dispose() {
    _questionTiming?.finish('cancelled');
    WidgetsBinding.instance.removeObserver(this);
    _chatScrollController.dispose();
    timer?.cancel();
    cueRefresh?.cancel();
    sprintRefresh?.cancel();
    sprintCountdown.dispose();
    _speechGeneration++;
    _speechRequest?.cancel();
    _playbackComplete?.cancel();
    _speechPlayback?.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) unawaited(_stopSpeech());
    sprintForeground = state == AppLifecycleState.resumed;
    sprintGeneration++;
    if (state == AppLifecycleState.resumed) {
      setState(() {
        sprint = null;
        sprintCountdown.update(null);
        hiddenSprintId = null;
      });
      _refreshSprint();
      _refreshCue();
      _scheduleCueRefresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(fit: StackFit.expand, children: [
        SafeArea(child: switch (tab) {
          0 => _home(context),
          1 => const WardWorksLibrary(),
          _ => _profile(context)
        }),
      ]),
      bottomNavigationBar: NavigationBar(
          selectedIndex: tab,
          onDestinationSelected: (value) {
            if (value != 0) unawaited(_stopSpeech());
            setState(() {
              if (value != 0) _discardSprintSetup();
              if (value == 0) hiddenSprintId = null;
              tab = value;
            });
            if (value == 0) _refreshSprint();
          },
          destinations: const [
            NavigationDestination(
                icon: Icon(Icons.home_outlined),
                selectedIcon: Icon(Icons.home),
                label: '首页'),
            NavigationDestination(
                icon: Icon(Icons.eco_outlined),
                selectedIcon: Icon(Icons.eco),
                label: '作品'),
            NavigationDestination(
                icon: Icon(Icons.person_outline),
                selectedIcon: Icon(Icons.person),
                label: '我的')
          ]),
    );
  }

  Widget _home(BuildContext context) {
    return Stack(children: [
      if (chatOpen) _chatOverlay() else _quietHome(),
        Positioned(left: 16, right: 16, bottom: 12, child: _chatEntry()),
    ]);
  }

  Widget _homeMenu() => PopupMenuButton<String>(
        tooltip: '更多',
        onSelected: (value) {
          switch (value) {
            case 'autoRead':
              _autoReadChanged = true;
              setState(() => _autoRead = !_autoRead);
              unawaited(ref.read(tokenStorageProvider).setAutoReadReplies(widget.wardId, _autoRead));
              if (!_autoRead) unawaited(_stopSpeech());
            case 'current':
              _openChat();
            case 'works':
              Navigator.push(context, MaterialPageRoute(builder: (_) => const WardWorksLibrary()));
            case 'history':
              _chooseThread();
            case 'sprint':
              _openSprint();
            case 'clear':
              _clearChatHistory();
          }
        },
        itemBuilder: (_) => [
          CheckedPopupMenuItem(value: 'autoRead', checked: _autoRead, child: const Text('自动朗读 Agent 回复')),
          PopupMenuItem(value: 'current', child: Text('当前对话')),
          PopupMenuItem(value: 'history', child: Text('历史对话')),
          PopupMenuItem(value: 'works', child: Text('我的作品')),
          PopupMenuItem(value: 'sprint', child: Text('专注挑战')),
          PopupMenuItem(value: 'clear', child: Text('清空当前对话')),
        ],
      );

  Widget? _activeSprintCard() =>
      sprint != null && hiddenSprintId != sprint!['id']
          ? SprintCard(
              sprint: sprint!,
              countdown: sprintCountdown,
              busy: sprintBusy,
              onAction: _actSprint,
              onHide: () =>
                  setState(() => hiddenSprintId = sprint!['id'] as String),
              onElapsed: _refreshSprint)
          : null;

  Widget _sprintHeaderAction({bool inChat = false}) =>
      ValueListenableBuilder<int>(
          valueListenable: sprintCountdown,
          builder: (context, remaining, _) => Tooltip(
              message: inChat ? '对话内专注挑战' : '查看专注挑战',
              child: TextButton(
                  style: TextButton.styleFrom(
                      foregroundColor:
                          Theme.of(context).colorScheme.onSurfaceVariant,
                      minimumSize: const Size(48, 48),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 6)),
                  onPressed: sprintBusy || _chatBusy ? null : _openSprint,
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const Icon(Icons.timer_outlined, size: 22),
                    if (remaining > 0 &&
                        hiddenSprintId == sprint?['id'] &&
                        !sprintSetupOpen) ...[
                      const SizedBox(height: 2),
                      SizedBox(
                          width: 64,
                          child: FittedBox(
                              fit: BoxFit.scaleDown,
                              child: Text(
                                  '${sprint?['status'] == 'paused' ? '已暂停 · ' : ''}${sprintTimeLabel(remaining)}',
                                  key: const Key('sprint-header-countdown'),
                                  style: TextStyle(
                                      fontSize: 11,
                                      height: 1.2,
                                      color: Theme.of(context)
                                          .colorScheme
                                          .onSurfaceVariant,
                                      fontFeatures: const [
                                        FontFeature.tabularFigures()
                                      ])))),
                    ],
                  ]))));

  Widget _quietHome() => Positioned.fill(
          child: Column(children: [
        Padding(
            padding: const EdgeInsets.fromLTRB(20, 8, 8, 8),
            child: Row(children: [
              const Expanded(
                  child: Text('读学',
                      style: TextStyle(
                          fontSize: 20, fontWeight: FontWeight.w700))),
              if (sprint != null) _sprintHeaderAction(),
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
                              icon: const Icon(
                                  Icons.local_fire_department_outlined),
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
                  ],
                ]))),
      ]));

  Widget _spokenSprintCard() => SprintPanel(
      title: '试一轮专注挑战',
      closeLabel: '取消专注挑战',
      onClose: sprintBusy ? null : () => setState(_discardSprintSetup),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
                color:
                    Theme.of(context).colorScheme.surface.withValues(alpha: .7),
                borderRadius: BorderRadius.circular(16)),
            child: Text(sprintSetupMessage,
                style: TextStyle(
                    fontSize:
                        spokenSprintPreview?['status'] == 'ready' ? 16 : 15,
                    fontWeight: spokenSprintPreview?['status'] == 'ready'
                        ? FontWeight.w600
                        : FontWeight.w400,
                    height: 1.4))),
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
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 8, children: [
            FilledButton.icon(
                onPressed: sprintBusy ? null : _startSpokenSprint,
                icon: const Icon(Icons.play_arrow_rounded, size: 20),
                label: Text(sprintBusy ? '开启中…' : '开始本轮')),
            TextButton.icon(
                onPressed: sprintBusy
                    ? null
                    : () => setState(() {
                          sprintSetupGeneration++;
                          spokenSprintPreview = null;
                          failedSprintSpeech = null;
                          sprintSetupMessage = '想改哪里？按住下面的说话按钮，再说一次。';
                        }),
                icon: const Icon(Icons.mic_none_rounded, size: 20),
                label: const Text('重新说')),
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
    _voiceDisplayText = null;
    recordingForSprint = sprintSetupOpen;
    recordingSetupGeneration = sprintSetupGeneration;
    await _stopSpeech();
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
      await _sendDraft(spoken: text, display: _voiceDisplayText);
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
            onTap: sprintSetupOpen ? null : _openChat,
            onBeforeRecording: _beforeHomeRecording,
            onPickImage: _pickChatImage,
            onVoiceDisplayText: sprintSetupOpen ? null : (text) => _voiceDisplayText = text,
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

  bool get _hasOlderHistory => nextBeforeThreadVersion != null;

  Widget _chatOverlay() {
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
            _ChatBubble(label: '读学 AI', text: '遇到问题随时问我；也可以试一轮专注挑战。'),
      ),
      for (final message in historyMessages) _chatMessage(message),
      for (final message in planMessages) _chatMessage(message),
      if (sprintAction != null)
        FilledButton(
            onPressed: _chatBusy ? null : _acceptSprintProposal,
            child: const Text('开始这次挑战')),
      if (clearingHistory)
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
                    _chatBusy ? null : () => _submitPlanInput(failedPlanText!,
                        attachmentKeys: _failedAttachmentKeys, display: _failedVoiceDisplay, commandId: _failedCommandId, pronunciation: _failedPronunciation),
                child: const Text('重试')),
          ]),
        ),
      if (!_messagesCarryPronunciation)
        for (final item in pronunciationLessons)
          Padding(
            padding: const EdgeInsets.only(top: 14),
            child: _pronunciationCard(item),
          ),
      if (planSending && _waitingForReply && !clearingHistory)
        ReplyProgress(
          stages: _replyStages,
          onRevealed: () => _scrollToChatBottom(onlyIfNearBottom: true),
        ),
      SizedBox(key: _chatTailKey, height: 1),
    ];

    return _HomeOverlay(
      banner: sprintSetupOpen ? _spokenSprintCard() : _activeSprintCard(),
      title: '读学',
      subtitle: '问功课，也可以聊聊好奇的事。',
      bottomInset: stagedImages.isNotEmpty ? 164 : 92,
      onClose: _closeHomeOverlay,
      closeTooltip: '收起对话',
      action: Row(mainAxisSize: MainAxisSize.min, children: [
        _sprintHeaderAction(inChat: true),
        _homeMenu(),
      ]),
      child: ListView.builder(
        key: const Key('companion-chat-list'),
        controller: _chatScrollController,
        padding: const EdgeInsets.all(16),
        itemCount: items.length,
        itemBuilder: (context, index) => items[index],
      ),
    );
  }

  Future<void> _chooseThread() async {
    if (clearingHistory) return;
    final id = await Navigator.of(context).push<String>(MaterialPageRoute(
      builder: (_) => ConversationPicker(api: ref.read(apiProvider), current: companionThreadId),
    ));
    if (!mounted || id == null) return;
    if (id != companionThreadId) {
      _replyAudio.clear();
      unawaited(_stopSpeech());
      setState(() {
        _resetThread();
        companionThreadId = id.isEmpty ? null : id;
      });
      final storage = ref.read(tokenStorageProvider);
      if (id.isEmpty) {
        await storage.clearCompanionThread();
      } else {
        await storage.saveCompanionThread(id, 0);
      }
      if (!mounted) return;
      try {
        await _refreshTranscript();
      } catch (_) {
        if (mounted) showMessage(context, '对话加载失败，请重新打开');
      }
    }
    if (mounted) _openChat();
  }

  void _resetThread() {
    _waitingForReply = false;
    _replyStages = const [];
    _questionTiming?.finish('cancelled');
    _chatGeneration++;
    planSending = false;
    planMessages.clear();
    historyMessages.clear();
    rememberedImages.clear();
    _imageLoads.clear();
    stagedImages.clear();
    _failedAttachmentKeys = const [];
    companionThreadId = null;
    companionThreadVersion = null;
    historyCursorThreadId = null;
    nextBeforeThreadVersion = null;
    loadingOlderMessages = false;
    _userScrolledAwayFromTop = false;
    failedPlanText = null;
    pronunciationLessons = const [];
    chatSubject = null;
  }

  Future<void> _clearChatHistory() async {
    if (clearingHistory) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('清空当前对话？'),
        content: const Text('清空当前对话中的消息。其他对话和已保存的作品会保留。'),
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
    setState(() => clearingHistory = true);
    var serverCleared = false;
    try {
      final id = companionThreadId;
      final result = id == null ? null : await ref.read(apiProvider).clearConversation(id);
      final version = result?['version'] as int?;
      serverCleared = true;
      _replyAudio.clear();
      await _stopSpeech();
      if (!mounted) return;
      setState(() {
        _resetThread();
        companionThreadId = id;
        companionThreadVersion = version;
      });
      if (id != null && version != null) {
        await ref.read(tokenStorageProvider).saveCompanionThread(id, version);
      }
      await _stopSpeech();
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

  void _closeHomeOverlay() {
    unawaited(_stopSpeech());
    setState(() {
      _discardSprintSetup();
      chatOpen = false;
      hiddenSprintId = null;
    });
    _refreshSprint();
  }

  void _openChat([String? subject]) {
    final wasOpen = chatOpen;
    setState(() {
      _discardSprintSetup();
      chatSubject = subject;
      chatOpen = true;
    });
    if (!wasOpen) {
      _scrollToChatBottom();
    }
  }

  Future<void> _sendDraft({String? spoken, String? display, bool pronunciation = false}) async {
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
    final attachments = stagedImages.where((image) => image.key != null).toList();
    final images = [for (final image in attachments) image.bytes];
    _openChat();
    setState(() {
      _anchorPronunciationLessons();
      stagedImages.removeWhere((image) => image.key != null);
      planMessages.add(_ChatLine(label: '我', content: content, images: images));
    });
    _scrollToChatBottom();
    await _submitPlanInput(content,
        attachmentKeys: [for (final image in attachments) image.key!],
        pronunciation: pronunciation, display: display);
  }

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

  String _newCommandId() =>
      List.generate(16, (_) => Random.secure().nextInt(256))
          .map((value) => value.toRadixString(16).padLeft(2, '0'))
          .join();

  Future<void> _refreshSprint() async {
    if (!sprintForeground) return;
    _presentSprintNotice();
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
        sprintCountdown.update(sprint);
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
            'command_id': _newCommandId(),
            'action': 'claim_notice',
            'expected_version': notice['version']
          });
        } catch (_) {
          return; // Another device may have claimed this notice; keep the verified round.
        }
        if (mounted) {
          // A successful claim must survive a new turn or foreground refresh.
          pendingSprintNotice = Map<String, dynamic>.from(notice);
          _presentSprintNotice();
        }
      }
    } catch (_) {
      // A missing/unavailable query is not evidence a round is still running.
      if (mounted && generation == sprintGeneration) {
        setState(() {
          sprint = null;
          sprintCountdown.update(null);
        });
      }
    }
  }

  void _presentSprintNotice() {
    if (!mounted || !sprintForeground || _chatBusy || sprintBusy) return;
    final notice = pendingSprintNotice;
    if (notice == null) return;
    pendingSprintNotice = null;
    showMessage(
        context,
        notice['status'] == 'ready'
            ? '约定的挑战时间到了，想开始时点“专注挑战”。'
            : '这轮计时结束了，要继续还是休息？');
  }

  Future<void> _openSprint() async {
    if (sprintBusy || _chatBusy) return;
    unawaited(_stopSpeech());
    final generation = ++sprintSetupGeneration;
    setState(() {
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
      pendingSprintRequest = {...data, 'command_id': _newCommandId()};
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
        'command_id': _newCommandId(),
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
    final generation = _chatGeneration;
    final speechGeneration = _speechGeneration;
    final onStage = _startCompanionReply();
    try {
      final result = await ref.read(apiProvider).companionTurn(
          content: '',
          onStage: onStage,
          threadId: companionThreadId,
          expectedThreadVersion: companionThreadVersion,
          structuredCommand: {
            'interaction_id': action['id'],
            'command': 'sprint_command',
            'payload': action['payload']
          });
      if (!mounted || generation != _chatGeneration) return;
      sprintAction = null;
      await _applyPlanTurnResult(result, speechGeneration: speechGeneration);
      await _refreshSprint();
    } catch (error) {
      if (mounted && generation == _chatGeneration) {
        showMessage(context, '请重新查看这轮挑战：${userErrorMessage(error)}');
      }
    } finally {
      if (mounted && generation == _chatGeneration) {
        setState(() => planSending = false);
        _presentSprintNotice();
      }
    }
  }

  Future<void> _load() async {
    try {
      profile = await ref.read(apiProvider).wardProfile();
    } catch (_) {}
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

  Future<void> _pickChatImage() async {
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
    _openChat();
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
      {required List<String> attachmentKeys, bool pronunciation = false, String? display, String? commandId}) async {
    if (_chatBusy) return;
    final speechGeneration = _speechGeneration;
    final timing = ref.read(conversationLatencyProvider).start('ward');
    _questionTiming = timing;
    final sendId = commandId ?? _newCommandId();
    final photoTimer = Stopwatch()..start();
    _photoCommandId = null;
    _photoLatency = null;
    final generation = _chatGeneration;
    final onStage = _startCompanionReply();
    try {
      if (companionThreadId == null) {
        final created = await ref.read(apiProvider).createConversation();
        if (!mounted || generation != _chatGeneration) return;
        companionThreadId = created['thread_id'] as String;
        companionThreadVersion = created['version'] as int;
        await ref.read(tokenStorageProvider).saveCompanionThread(companionThreadId!, companionThreadVersion!);
        if (!mounted || generation != _chatGeneration) return;
      }
      final result = await timing.request(() => ref.read(apiProvider).companionTurn(
          content: text,
          commandId: sendId,
          onStage: onStage,
          voiceDisplayText: display,
          threadId: companionThreadId,
          expectedThreadVersion: companionThreadVersion,
          attachmentKeys: attachmentKeys,
          routeHint: pronunciation ? 'tutoring' : null,
          tutoringIntent: pronunciation ? 'pronunciation' : null));
      if (!mounted || generation != _chatGeneration) return;
      _photoCommandId = result['command_id'] as String?;
      _photoLatency = photoTimer;
      await _applyPlanTurnResult(result, speechGeneration: speechGeneration, timing: timing);
    } catch (error) {
      timing.fail(error);
      if (!mounted || generation != _chatGeneration) return;
      if (mounted && generation == _chatGeneration) {
        _scrollToChatBottom(onlyIfNearBottom: true);
        setState(() {
          failedPlanText = text;
          _failedCommandId = sendId;
          _failedPronunciation = pronunciation;
          _failedAttachmentKeys = attachmentKeys;
          _failedVoiceDisplay = display;
        });
        showMessage(context, '暂时无法整理今天的计划，请重试');
      }
    } finally {
      if (mounted && generation == _chatGeneration) {
        setState(() => planSending = false);
        _presentSprintNotice();
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
    final speechGeneration = _speechGeneration;
    final onStage = _startCompanionReply();
    try {
      final result = await ref.read(apiProvider).companionTurn(
        content: '选择：${action['label']}',
        onStage: onStage,
        threadId: companionThreadId,
        expectedThreadVersion: companionThreadVersion,
        structuredCommand: {
          'interaction_id': action['id'],
          'command': 'choose_intent',
          'payload': action['payload'],
        },
      );
      if (!mounted || generation != _chatGeneration) return;
      await _applyPlanTurnResult(result, speechGeneration: speechGeneration);
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
        _presentSprintNotice();
      }
    }
  }

  Future<void> _applyPlanTurnResult(Map<String, dynamic> result, {required int speechGeneration, ConversationTurn? timing}) async {
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
    Map<String, dynamic>? lesson;
    if (interaction['kind'] == 'pronunciation_lesson' &&
        objectRef['object_id'] is String) {
      lesson = await ref
          .read(apiProvider)
          .pronunciationLesson(objectRef['object_id'] as String);
    }
    if (!mounted || generation != _chatGeneration) return;
    setState(() {
      final quiet = interaction['observation_quiet'];
      if (quiet is Map && quiet['ward_version'] is int && quiet['ward_version'] > _quietVersion) {
        _quietVersion = quiet['ward_version'] as int;
      }
      failedPlanText = null;
      _failedAttachmentKeys = const [];
      final rawLessons = lesson?['lessons'] ?? interaction['lessons'];
      pronunciationLessons = rawLessons is List && rawLessons.isNotEmpty
          ? [
              for (final item in rawLessons)
                if (item is Map) Map<String, dynamic>.from(item),
            ]
          : (lesson != null ? [lesson] : const []);
      sprintAction = null;
      for (final action in actions) {
        if (action['command'] == 'sprint_command' &&
            action['enabled'] == true) {
          sprintAction = action;
        }
      }
    });
    await _refreshTranscript(completesReply: true, timing: timing);
    if (!mounted || !sprintForeground || !_autoRead || tab != 0 || !chatOpen ||
        generation != _chatGeneration || speechGeneration != _speechGeneration) {
      return;
    }
    final commandId = result['command_id'];
    if (commandId == null) return;
    for (final message in planMessages.reversed) {
      if (message.readable && message.commandId == commandId) {
        unawaited(_readReply(message));
        break;
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
        content: (item['author_type'] == 'ward' ? (interactionRef?['voice_display_text'] as String?) : null) ?? item['content'] as String,
        readable: item['can_read_aloud'] == true && item['id'] is String,
        commandId: item['command_id'] as String?,
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
        claimPlayback: () {
          unawaited(_stopSpeech());
          final generation = _speechGeneration;
          _playbackClaimed = true;
          return () => generation == _speechGeneration;
        },
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
                onPhotoVisible: message.visual?['kind'] == 'web_photo'
                    ? () => _photoVisible(message.commandId)
                    : null,
                visual: message.visual),
            if (message.interactionRef?['artifact_id'] case final String id)
              OutlinedButton.icon(icon: const Icon(Icons.menu_book), label: const Text('打开绘本'),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => WardStoryPage(id: id)))),
            if (message.readable)
              TextButton.icon(
                onPressed: () => _readReply(message),
                icon: Icon(_readingId == message.id ? Icons.stop : Icons.volume_up_outlined),
                label: Text(_readingId == message.id ? '停止朗读' : '朗读'),
              ),
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

  void _scrollToChatBottom({bool onlyIfNearBottom = false}) {
    if (onlyIfNearBottom &&
        (!_chatScrollController.hasClients ||
            _chatScrollController.position.extentAfter > 32)) {
      return;
    }
    final revision = ++_chatScrollRevision;
    final generation = _chatGeneration;
    var remainingFrames = 12;
    void follow(Duration _) {
      if (!mounted ||
          revision != _chatScrollRevision ||
          generation != _chatGeneration ||
          !chatOpen ||
          !_chatScrollController.hasClients) {
        return;
      }
      final position = _chatScrollController.position;
      if (position.userScrollDirection != ScrollDirection.idle) return;
      if ((position.pixels - position.maxScrollExtent).abs() > 0.5) {
        _chatScrollController.jumpTo(position.maxScrollExtent);
      }
      // A lazy list estimates its extent until the last rows are laid out.
      // Correct from the next layout when a jump has not reached the tail.
      if (_chatTailKey.currentContext == null && --remainingFrames > 0) {
        WidgetsBinding.instance.addPostFrameCallback(follow);
        WidgetsBinding.instance.ensureVisualUpdate();
      }
    }

    WidgetsBinding.instance.addPostFrameCallback(follow);
  }

  // Only auto-load on scroll after the user has scrolled away from the top
  // and then scrolls back up near the top; prevents auto-fetching every page
  // immediately when the list first renders at pixels == 0.
  bool _userScrolledAwayFromTop = false;
  void _onChatScroll() {
    if (!chatOpen ||
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
    final targetThreadId = historyCursorThreadId ?? companionThreadId;
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

  Future<void> _refreshTranscript({
    bool completesReply = false,
    ConversationTurn? timing,
  }) async {
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
    if (completesReply) _scrollToChatBottom(onlyIfNearBottom: true);
    setState(() {
      if (completesReply) _waitingForReply = false;
      if (resolvedThreadId != null) {
        companionThreadId = resolvedThreadId;
      }
      companionThreadVersion = version;
      if (historyMessages.isEmpty) {
        historyCursorThreadId = resolvedThreadId;
        nextBeforeThreadVersion =
            transcript['next_before_thread_version'] as int?;
      } else {
        historyMessages
            .removeWhere((m) => m.id != null && latestIds.contains(m.id));
      }
      planMessages
        ..clear()
        ..addAll(latestLines);
      if (latestLines.any((message) => message.lessons.isNotEmpty)) {
        pronunciationLessons = const [];
      }
    });
    timing?.finish('success');
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
    this.commandId,
    this.readable = false,
    this.visual,
    this.lessons = const [],
    this.intentActions = const [],
    this.interactionRef,
  });
  final String? id;
  final String? threadId;
  final int? threadVersion;
  final String? commandId;
  final bool readable;
  final String label;
  final String content;
  final List<Uint8List> images;
  final List<String> imageRefs;
  final Map<String, dynamic>? visual;
  final List<Map<String, dynamic>> lessons;
  final List<Map<String, dynamic>> intentActions;
  final Map<String, dynamic>? interactionRef;

  _ChatLine copyWith(
          {List<Map<String, dynamic>>? lessons,
          Map<String, dynamic>? interactionRef}) =>
      _ChatLine(
        id: id,
        threadId: threadId,
        threadVersion: threadVersion,
        commandId: commandId,
        readable: readable,
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
    this.onPhotoVisible,
    this.loadImage,
    this.visual,
  });
  final String label;
  final String text;
  final List<Uint8List> images;
  final int imageCount;
  final VoidCallback? onPhotoVisible;
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
      final photoWidth = (maxWidth - 26).clamp(1.0, 320.0).toDouble();
      final previewWidth = onPhotoVisible == null ? 72.0 : photoWidth;
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
                                        width: previewWidth,
                                        height: onPhotoVisible == null ? 72 : null,
                                        fit: onPhotoVisible == null ? BoxFit.cover : BoxFit.contain,
                                        cacheWidth: chatImageCachePixels(previewWidth,
                                            MediaQuery.devicePixelRatioOf(context)),
                                        cacheHeight: onPhotoVisible == null ? chatImageCachePixels(72, MediaQuery.devicePixelRatioOf(context)) : null,
                                        frameBuilder: onPhotoVisible == null ? null :
                                            (context, child, frame, sync) {
                                          if (frame != null || sync) {
                                            WidgetsBinding.instance.addPostFrameCallback((_) => onPhotoVisible!());
                                          }
                                          return child;
                                        },
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
