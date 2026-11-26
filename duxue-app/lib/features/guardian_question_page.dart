import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../core/speech_playback.dart';
import '../core/user_error_message.dart';
import '../providers.dart';
import '../core/conversation_latency.dart';
import '../shared/app_ui.dart';
import '../shared/chat_markdown.dart';
import '../shared/reply_progress.dart';
import '../shared/voice_composer.dart';
import 'guardian_courseware/guardian_courseware_page.dart';
import 'pronunciation_player.dart';
import 'visual_block.dart';

typedef _PickedPicture = ({Uint8List bytes, String extension, String? key});

class _PerspectiveSession {
  final messages = <Map<String, dynamic>>[];
  final pictures = <_PickedPicture>[];
  String draftText = '';
  String? stateToken, error, pendingQuestion;
  final stages = <ReplyStage>[];
  List<Uint8List> pendingPictures = const [];
  List<String>? retryKeys;
  String? retryStartToken;
  bool busy = false, expired = false;
  int generation = 0;
  ConversationTurn? timing;

  void clear() {
    timing?.finish('cancelled');
    generation++;
    messages.clear();
    pictures.clear();
    draftText = '';
    stateToken = null;
    error = null;
    pendingQuestion = null;
    stages.clear();
    pendingPictures = const [];
    retryKeys = null;
    retryStartToken = null;
    busy = false;
    expired = false;
  }
}

class GuardianQuestionPage extends ConsumerStatefulWidget {
  const GuardianQuestionPage({required this.active, super.key});
  final bool active;
  @override
  ConsumerState<GuardianQuestionPage> createState() =>
      _GuardianQuestionPageState();
}

class _GuardianQuestionPageState extends ConsumerState<GuardianQuestionPage> {
  static const _studentMode = 'student_guide';
  static const _mentorMode = 'guardian_explain';
  static const _exampleQuestion = '3/4 和 2/3 哪个大？';

  final input = TextEditingController();
  final focus = FocusNode();
  final scroll = ScrollController();
  final _sessions = <String, _PerspectiveSession>{
    _studentMode: _PerspectiveSession(),
    _mentorMode: _PerspectiveSession(),
  };
  String mode = _mentorMode;
  bool keyboard = false;
  SpeechPlayback? _playback;
  SpeechPlayback get playback => _playback ??= DeviceSpeechPlayback();

  _PerspectiveSession get _cur => _sessions[mode]!;

  @override
  void didUpdateWidget(GuardianQuestionPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.active) {
      focus.unfocus();
      _playback?.stop();
    }
  }

  @override
  void dispose() {
    for (final s in _sessions.values) {
      s.timing?.finish('cancelled');
      s.generation++;
    }
    input.dispose();
    focus.dispose();
    scroll.dispose();
    _playback?.dispose();
    super.dispose();
  }

  void _bottom({bool onlyIfNearBottom = false}) {
    if (onlyIfNearBottom &&
        (!scroll.hasClients || scroll.position.extentAfter > 32)) {
      return;
    }
    final currentMode = mode;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted ||
          !widget.active ||
          mode != currentMode ||
          !scroll.hasClients) {
        return;
      }
      final end = scroll.position.maxScrollExtent;
      if (MediaQuery.disableAnimationsOf(context)) {
        scroll.jumpTo(end);
      } else {
        scroll.animateTo(end,
            duration: const Duration(milliseconds: 220), curve: Curves.easeOut);
      }
    });
  }

  void _switchMode(String nextMode) {
    if (mode == nextMode) return;
    _cur.draftText = input.text;
    _playback?.stop();
    focus.unfocus();
    setState(() {
      mode = nextMode;
      final restored = _cur.draftText;
      input.value = TextEditingValue(
        text: restored,
        selection: TextSelection.collapsed(offset: restored.length),
      );
    });
    _bottom();
  }

  Future<void> _clear() async {
    final isMentor = mode == _mentorMode;
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: const Text('重新开始问答？'),
                content: Text(isMentor ? '将清空当前导师视角对话。' : '将清空本轮体验对话。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  TextButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('重新开始')),
                ]));
    if (!mounted || confirmed != true) return;
    _playback?.stop();
    setState(() {
      _cur.clear();
      input.clear();
    });
  }

  Future<void> _pick() async {
    final session = _cur;
    if (session.busy || session.pictures.length >= 4) return;
    final epoch = session.generation;
    try {
      final file = await ImagePicker().pickImage(
          source: ImageSource.camera, maxWidth: 1920, imageQuality: 85);
      if (file == null) return;
      final bytes = await file.readAsBytes();
      if (!mounted || epoch != session.generation) return;
      final extension =
          file.name.toLowerCase().endsWith('.png') ? 'png' : 'jpg';
      setState(() =>
          session.pictures.add((bytes: bytes, extension: extension, key: null)));
    } catch (e) {
      if (mounted && epoch == session.generation) {
        showMessage(context, '暂时无法拍照：${userErrorMessage(e)}');
      }
    }
  }

  Map<String, dynamic>? _lastStudentUserQuestion() {
    final list = _sessions[_studentMode]!.messages;
    final originId = list.lastOrNull?['mentor_origin_turn_id'];
    if (originId != null) {
      for (var i = list.length - 2; i >= 0; i--) {
        if (list[i]['role'] == 'user' && list[i]['turn_id'] == originId) {
          return list[i];
        }
      }
    }
    for (var i = list.length - 1; i >= 0; i--) {
      if (list[i]['role'] == 'user') return list[i];
    }
    return null;
  }

  Future<void> _revealInMentor() async {
    final source = _lastStudentUserQuestion();
    if (source == null) return;
    final mentorSession = _sessions[_mentorMode]!;
    if (mentorSession.busy) {
      _switchMode(_mentorMode);
      return;
    }
    final questionText = (source['content'] as String? ?? '').trim();
    final sourcePictures =
        (source['pictures'] as List? ?? const []).cast<Uint8List>();
    final sourceKeys =
        (source['attachment_keys'] as List? ?? const []).cast<String>();
    _switchMode(_mentorMode);
    await _dispatchTurn(
      targetMode: _mentorMode,
      content: questionText,
      startToken: _sessions[_studentMode]!.messages.last['mentor_start_token'] as String?,
      preUploadedPictures: sourcePictures,
      preUploadedKeys: sourceKeys,
      useComposerDraft: false,
    );
  }

  Future<void> _send([String? spoken]) async {
    final session = _cur;
    if (session.busy || session.expired) return;
    if (spoken == null &&
        input.text.trim().isEmpty &&
        session.pictures.isEmpty &&
        session.retryKeys != null &&
        (session.pendingQuestion ?? '').isNotEmpty) {
      await _dispatchTurn(
        targetMode: mode,
        content: session.pendingQuestion!,
        startToken: session.retryStartToken,
        preUploadedPictures: session.pendingPictures,
        preUploadedKeys: session.retryKeys,
        useComposerDraft: false,
      );
      return;
    }
    final content = (spoken ?? input.text).trim();
    if (content.isEmpty && session.pictures.isEmpty) return;
    input.clear();
    session.draftText = '';
    focus.unfocus();
    await _dispatchTurn(
      targetMode: mode,
      content: content,
      useComposerDraft: true,
    );
  }

  Future<void> _dispatchTurn({
    required String targetMode,
    required String content,
    String? startToken,
    List<Uint8List>? preUploadedPictures,
    List<String>? preUploadedKeys,
    required bool useComposerDraft,
  }) async {
    final session = _sessions[targetMode]!;
    if (session.busy || (session.expired && useComposerDraft)) return;
    final timing = ref.read(conversationLatencyProvider).start('guardian');
    session.timing = timing;
    final epoch = session.generation;
    final displayPictures = preUploadedPictures ??
        [for (final picture in session.pictures) picture.bytes];
    final uploadsImages = preUploadedKeys == null &&
        session.pictures.any((picture) => picture.key == null);
    setState(() {
      session.busy = true;
      session.stages
        ..clear()
        ..add(uploadsImages ? ReplyStage.uploading : ReplyStage.preparing);
      session.error = null;
      session.pendingQuestion = content;
      session.pendingPictures = displayPictures;
      session.retryKeys = preUploadedKeys;
      session.retryStartToken = startToken;
    });
    _bottom();
    try {
      final api = ref.read(apiProvider);
      final List<String> attachmentKeys;
      if (preUploadedKeys != null) {
        attachmentKeys = preUploadedKeys;
      } else {
        for (var i = 0; i < session.pictures.length; i++) {
          final picture = session.pictures[i];
          if (picture.key != null) continue;
          final key = await api.uploadGuardianExperienceImage(
              picture.bytes, picture.extension);
          if (!mounted || epoch != session.generation) return;
          session.pictures[i] =
              (bytes: picture.bytes, extension: picture.extension, key: key);
        }
        attachmentKeys = [for (final picture in session.pictures) picture.key!];
      }
      if (uploadsImages) {
        if (mode == targetMode) _bottom(onlyIfNearBottom: true);
        setState(() => session.stages.add(ReplyStage.preparing));
      }
      final response = await timing.request(() => api.guardianExperienceTurn(
            content: content,
            stateToken: useComposerDraft ? session.stateToken : startToken,
            attachmentKeys: attachmentKeys,
            mode: targetMode,
            onStage: (stage) {
              final nextStage = ReplyStage.fromWire(stage);
              if (mounted &&
                  epoch == session.generation &&
                  identical(session.timing, timing) &&
                  session.busy &&
                  nextStage != null &&
                  session.stages.last != nextStage) {
                if (mode == targetMode) _bottom(onlyIfNearBottom: true);
                setState(() => session.stages.add(nextStage));
              }
            },
          ));
      if (!mounted || epoch != session.generation) return;
      if (mode == targetMode) _bottom(onlyIfNearBottom: true);
      setState(() {
        session.messages.add({
          'role': 'user',
          'turn_id': response['turn_id'],
          'content': content,
          'pictures': displayPictures,
          'attachment_keys': attachmentKeys,
        });
        session.messages.add({
          'role': 'assistant',
          'source_prompt': content,
          'source_keys': attachmentKeys,
          ...response,
        });
        session.stateToken = response['state_token'] as String?;
        if (useComposerDraft) {
          session.pictures.clear();
          if (mode == targetMode) input.clear();
        }
        session.retryKeys = null;
        session.retryStartToken = null;
        session.expired = false;
        session.pendingPictures = const [];
      });
      timing.finish('success');
    } catch (e) {
      timing.fail(e);
      if (!mounted || epoch != session.generation) return;
      if (mode == targetMode) _bottom(onlyIfNearBottom: true);
      final detailCode = e is DioException &&
              e.response?.data is Map &&
              (e.response!.data as Map)['detail'] is Map
          ? ((e.response!.data as Map)['detail'] as Map)['code']
          : null;
      setState(() {
        if (useComposerDraft) {
          session.draftText = content;
          if (mode == targetMode) input.text = content;
        }
        session.expired = detailCode == 'experience_expired';
        if (session.expired) {
          session.error = '本轮对话已过期，请重新开始。';
        } else if (detailCode == 'mentor_rate_limited') {
          session.error = '导师深度解析请求较频繁，请稍后再试或切换学生视角体验。';
        } else {
          session.error = '这次没能发送成功，请重试。';
        }
      });
    } finally {
      if (mounted && epoch == session.generation) {
        setState(() {
          session.busy = false;
          if (session.error == null) {
            session.pendingQuestion = null;
          }
        });
      }
    }
  }

  Widget _modeChip({
    required String value,
    required String label,
    required IconData icon,
  }) {
    final selected = mode == value;
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      selected: selected,
      child: InkWell(
        key: ValueKey('mode-$value'),
        borderRadius: BorderRadius.circular(999),
        onTap: () => _switchMode(value),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: selected ? scheme.primaryContainer : Colors.transparent,
            borderRadius: BorderRadius.circular(999),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon,
                size: 15,
                color: selected ? scheme.onPrimaryContainer : Colors.blueGrey),
            const SizedBox(width: 4),
            Text(label,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                  color: selected ? scheme.onPrimaryContainer : Colors.blueGrey,
                )),
          ]),
        ),
      ),
    );
  }

  bool get _canRevealInMentor {
    if (mode != _studentMode) return false;
    final session = _sessions[_studentMode]!;
    if (session.busy || session.messages.isEmpty) return false;
    final last = session.messages.last;
    if (last['role'] != 'assistant') return false;
    final act = last['act'] as String?;
    return act != 'safety' &&
        act != 'unavailable' &&
        _lastStudentUserQuestion() != null;
  }

  @override
  Widget build(BuildContext context) {
    final session = _cur;
    final isMentor = mode == _mentorMode;
    return Column(children: [
      Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 2),
          child: Row(children: [
            Expanded(
              child: Align(
                alignment: Alignment.centerLeft,
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Container(
                    padding: const EdgeInsets.all(2),
                    decoration: BoxDecoration(
                      color: const Color(0xfff1f5f9),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      _modeChip(
                        value: _studentMode,
                        label: '体验孩子怎么学',
                        icon: Icons.school_outlined,
                      ),
                      _modeChip(
                        value: _mentorMode,
                        label: '看导师怎么讲',
                        icon: Icons.auto_awesome_outlined,
                      ),
                    ]),
                  ),
                ),
              ),
            ),
            if (session.messages.isNotEmpty ||
                session.busy ||
                session.error != null)
              IconButton(
                  tooltip: '重新开始问答',
                  onPressed: _clear,
                  icon: const Icon(Icons.add_comment_outlined)),
          ])),
      Expanded(
          child: ListView(
              controller: scroll,
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
              children: [
            if (session.messages.isEmpty &&
                !session.busy &&
                session.error == null) ...[
              const SizedBox(height: 24),
              Text(
                  isMentor
                      ? '拍一道题，或说出题目，看看导师怎么完整讲解。'
                      : '拍一道题，或说出题目，看看 AI 怎么一步步引导孩子。',
                  style: Theme.of(context).textTheme.titleLarge),
              if (!keyboard && session.pictures.isEmpty) ...[
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: session.expired
                        ? null
                        : () => _send(_exampleQuestion),
                    child: const Text('用一道示例题'),
                  ),
                ),
              ],
            ],
            for (var index = 0; index < session.messages.length; index++)
              _message(session.messages[index], index),
            if (session.busy || session.error != null)
              _message({
                'role': 'user',
                'content': session.pendingQuestion ?? input.text,
                'pictures': session.pendingPictures.isNotEmpty
                    ? session.pendingPictures
                    : [for (final picture in session.pictures) picture.bytes]
              }, session.messages.length),
            if (session.busy && widget.active)
              ReplyProgress(
                key: ObjectKey(session),
                stages: session.stages,
                onRevealed: () => _bottom(onlyIfNearBottom: true),
              ),
            if (session.error != null)
              Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Row(children: [
                    Expanded(
                        child: Text(session.error!,
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error))),
                    TextButton(
                        onPressed: session.expired ? _clear : () => _send(),
                        child: Text(session.expired ? '重新开始' : '重试')),
                  ])),
            if (_canRevealInMentor)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: _revealInMentor,
                    child: const Text('看这道题的完整讲解'),
                  ),
                ),
              ),
          ])),
      if (session.pictures.isNotEmpty && !session.busy)
        SizedBox(
            height: 90,
            child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                children: [
                  for (var i = 0; i < session.pictures.length; i++)
                    Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: Stack(children: [
                          ClipRRect(
                              borderRadius: BorderRadius.circular(10),
                              child: Image.memory(session.pictures[i].bytes,
                                  width: 80, height: 80, fit: BoxFit.cover)),
                          Positioned(
                              right: 0,
                              top: 0,
                              child: IconButton.filledTonal(
                                  tooltip: '移除照片',
                                  onPressed: session.busy
                                      ? null
                                      : () => setState(
                                          () => session.pictures.removeAt(i)),
                                  icon: const Icon(Icons.close, size: 16)))
                        ])),
                ])),
      Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
          child: keyboard
              ? Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  IconButton(
                      tooltip: '切换语音',
                      onPressed: session.busy
                          ? null
                          : () {
                              focus.unfocus();
                              setState(() => keyboard = false);
                            },
                      icon: const Icon(Icons.mic_none)),
                  Expanded(
                      child: TextField(
                          controller: input,
                          focusNode: focus,
                          enabled: !session.busy && !session.expired,
                          minLines: 1,
                          maxLines: 4,
                          maxLength: 2400,
                          onChanged: (val) => session.draftText = val,
                          textInputAction: TextInputAction.newline,
                          decoration: InputDecoration(
                              hintText:
                                  isMentor ? '输入题目，直接看完整思路与解答' : '输入你的问题',
                              counterText: '',
                              isDense: true))),
                  IconButton(
                      tooltip: '拍照',
                      onPressed: session.busy ||
                              session.expired ||
                              session.pictures.length >= 4
                          ? null
                          : _pick,
                      icon: const Icon(Icons.camera_alt_outlined)),
                  IconButton.filled(
                      tooltip: '发送问题',
                      onPressed:
                          session.busy || session.expired ? null : () => _send(),
                      icon: const Icon(Icons.arrow_upward, size: 20)),
                ])
              : !widget.active
                  ? const SizedBox(height: 52)
                  : VoiceComposer(
                      baseUrl: apiBaseUrl,
                      tokens: ref.read(tokenStorageProvider),
                      telemetry: ref.read(telemetryProvider),
                      enabled:
                          widget.active && !session.busy && !session.expired,
                      onVoiceFinal: _send,
                      onPickImage: _pick,
                      helperText: session.pictures.isEmpty
                          ? (isMentor
                              ? '轻点打字 · 按住说题看完整解析'
                              : '轻点打字 · 按住说话')
                          : '轻点打字，或按住说说想问什么',
                      onTap: () {
                        setState(() => keyboard = true);
                        focus.requestFocus();
                      })),
      if (session.pictures.isNotEmpty && !keyboard)
        TextButton(
            onPressed: session.busy || session.expired ? null : () => _send(),
            child: const Text('发送照片')),
    ]);
  }

  Widget _verificationBadge(Map<String, dynamic> verification) {
    final status = verification['status'] as String?;
    final confidence = verification['confidence'] as String?;
    final needsConfirm = verification['needs_condition_confirmation'] == true;
    final verified = verification['draft_reviewed'] == true && !needsConfirm &&
        status == 'ready' &&
        (confidence == 'high' || confidence == 'medium');
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: verified ? const Color(0xffecfdf5) : const Color(0xfffffbeb),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(
            verified ? Icons.verified_outlined : Icons.info_outline,
            size: 14,
            color: verified ? const Color(0xff0f766e) : const Color(0xffb45309),
          ),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              verified ? '解析已复核' : '导师视角 · 思路参考（建议核对原题条件）',
              style: TextStyle(
                fontSize: 12,
                color: verified
                    ? const Color(0xff0f766e)
                    : const Color(0xffb45309),
              ),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _message(Map<String, dynamic> message, int index) {
    final mine = message['role'] == 'user';
    final text = message['content'] as String? ?? '';
    return Align(
        alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
            key: ValueKey('experience-message-$mode-$index'),
            constraints: BoxConstraints(
                maxWidth: MediaQuery.sizeOf(context).width * (mine ? 0.78 : 1)),
            margin: const EdgeInsets.only(top: 16),
            padding: mine
                ? const EdgeInsets.all(14)
                : const EdgeInsets.symmetric(vertical: 8),
            decoration: mine
                ? BoxDecoration(
                    color: const Color(0xffe8eef8),
                    borderRadius: BorderRadius.circular(14))
                : null,
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (!mine && message['verification'] is Map)
                _verificationBadge(
                    Map<String, dynamic>.from(message['verification'] as Map)),
              for (final bytes in (message['pictures'] as List? ?? const [])
                  .cast<Uint8List>())
                Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: Image.memory(bytes,
                            width: 160, height: 160, fit: BoxFit.cover))),
              if (text.isNotEmpty) ChatMarkdownBody(text: text),
              if (message['visual'] is Map)
                Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: VisualBlock(
                        visual: Map<String, dynamic>.from(
                            message['visual'] as Map))),
              for (final lesson in message['lessons'] as List? ?? const [])
                Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: PronunciationLessonCard(
                        lesson: Map<String, dynamic>.from(lesson as Map),
                        playback: playback,
                        loadSpeech:
                            ref.read(apiProvider).guardianExperienceSpeech)),
              if (!mine &&
                  mode == _mentorMode &&
                  message['recommend_courseware'] == true)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: FilledButton.tonalIcon(
                    onPressed: () {
                      Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) => GuardianCoursewarePage(
                            promptText:
                                (message['source_prompt'] as String?) ?? text,
                            attachmentKeys:
                                ((message['source_keys'] as List?) ?? const [])
                                    .cast<String>(),
                          ),
                        ),
                      );
                    },
                    icon: const Icon(Icons.auto_awesome, size: 16),
                    label: const Text('生成深度课件'),
                  ),
                ),
            ])));
  }
}
