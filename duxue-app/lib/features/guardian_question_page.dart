import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../core/speech_playback.dart';
import '../core/user_error_message.dart';
import '../providers.dart';
import '../shared/app_ui.dart';
import '../shared/chat_markdown.dart';
import '../shared/voice_composer.dart';
import 'pronunciation_player.dart';
import 'visual_block.dart';

typedef _PickedPicture = ({Uint8List bytes, String extension, String? key});

class _PerspectiveSession {
  final messages = <Map<String, dynamic>>[];
  final pictures = <_PickedPicture>[];
  String draftText = '';
  String? stateToken, error, pendingQuestion;
  List<Uint8List> pendingPictures = const [];
  List<String>? retryKeys;
  bool busy = false, expired = false;
  int generation = 0;

  void clear() {
    generation++;
    messages.clear();
    pictures.clear();
    draftText = '';
    stateToken = null;
    error = null;
    pendingQuestion = null;
    pendingPictures = const [];
    retryKeys = null;
    busy = false;
    expired = false;
  }
}

class GuardianQuestionPage extends ConsumerStatefulWidget {
  const GuardianQuestionPage(
      {required this.active, required this.onStartWithChild, super.key});
  final bool active;
  final VoidCallback onStartWithChild;
  @override
  ConsumerState<GuardianQuestionPage> createState() =>
      _GuardianQuestionPageState();
}

class _GuardianQuestionPageState extends ConsumerState<GuardianQuestionPage> {
  static const _studentMode = 'student_guide';
  static const _mentorMode = 'guardian_explain';

  final input = TextEditingController();
  final focus = FocusNode();
  final scroll = ScrollController();
  final _sessions = <String, _PerspectiveSession>{
    _studentMode: _PerspectiveSession(),
    _mentorMode: _PerspectiveSession(),
  };
  String mode = _studentMode;
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
      s.generation++;
    }
    input.dispose();
    focus.dispose();
    scroll.dispose();
    _playback?.dispose();
    super.dispose();
  }

  void _bottom() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && scroll.hasClients) {
          scroll.animateTo(scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 220),
              curve: Curves.easeOut);
        }
      });

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
    List<Uint8List>? preUploadedPictures,
    List<String>? preUploadedKeys,
    required bool useComposerDraft,
  }) async {
    final session = _sessions[targetMode]!;
    if (session.busy || session.expired) return;
    final epoch = session.generation;
    final displayPictures = preUploadedPictures ??
        [for (final picture in session.pictures) picture.bytes];
    setState(() {
      session.busy = true;
      session.error = null;
      session.pendingQuestion = content;
      session.pendingPictures = displayPictures;
      session.retryKeys = preUploadedKeys;
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
      final response = await api.guardianExperienceTurn(
        content: content,
        stateToken: session.stateToken,
        attachmentKeys: attachmentKeys,
        mode: targetMode,
      );
      if (!mounted || epoch != session.generation) return;
      setState(() {
        session.messages.add({
          'role': 'user',
          'content': content,
          'pictures': displayPictures,
          'attachment_keys': attachmentKeys,
        });
        session.messages.add({'role': 'assistant', ...response});
        session.stateToken = response['state_token'] as String?;
        if (useComposerDraft) {
          session.pictures.clear();
          if (mode == targetMode) input.clear();
        }
        session.retryKeys = null;
        session.pendingPictures = const [];
      });
      _bottom();
    } catch (e) {
      if (!mounted || epoch != session.generation) return;
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
    final examples = isMentor
        ? const [
            ('看应用题完整解析', '一桶油连桶重 12 千克，用去一半油后连桶重 7 千克，求油和桶各重多少？请给完整破题思路与易错点。', Icons.psychology_outlined),
            ('看分数比较讲题教案', '3/4 和 2/3 怎样比较大小？请给家长讲题思路与常见卡点。', Icons.menu_book_outlined),
          ]
        : const [
            ('试一道题', '请带我理解：3/4 和 2/3 怎样比较大小？', Icons.lightbulb_outline),
            ('问个知识点', '请用生活中的例子解释什么是比喻。', Icons.menu_book_outlined),
            ('听听发音', '请示范 apple 的发音。', Icons.volume_up_outlined),
          ];

    return Column(children: [
      Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 2),
          child: Row(children: [
            const Text('体验 AI 伴学',
                style: TextStyle(fontSize: 15, color: Colors.blueGrey)),
            const SizedBox(width: 10),
            Expanded(
              child: Align(
                alignment: Alignment.centerRight,
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerRight,
                  child: Container(
                    padding: const EdgeInsets.all(2),
                    decoration: BoxDecoration(
                      color: const Color(0xfff1f5f9),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      _modeChip(
                        value: _studentMode,
                        label: '学生视角',
                        icon: Icons.school_outlined,
                      ),
                      _modeChip(
                        value: _mentorMode,
                        label: '导师视角',
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
                      ? '切换导师视角，\n直接看完整思路与解答。'
                      : '先试一题，\n看看怎样一步步想明白。',
                  style: const TextStyle(
                      fontSize: 26,
                      height: 1.45,
                      fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              Text(
                  isMentor
                      ? '展示考点本质、完整破题推导与孩子高频易错点，帮助你快速评估导师功底或备课点拨。'
                      : '拍一道题，或说出你的问题。\n你可以像孩子一样追问、尝试。',
                  style: const TextStyle(color: Colors.blueGrey, height: 1.6)),
              const SizedBox(height: 28),
              for (final example in examples)
                Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 16, vertical: 15),
                            side: const BorderSide(color: Color(0xffe2e8f0)),
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(14))),
                        onPressed: session.busy || session.expired
                            ? null
                            : () => _send(example.$2),
                        child: Row(children: [
                          Icon(example.$3, size: 20),
                          const SizedBox(width: 12),
                          Expanded(child: Text(example.$1)),
                          const Icon(Icons.arrow_forward, size: 17)
                        ]))),
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
            if (session.busy)
              Padding(
                  padding: const EdgeInsets.symmetric(vertical: 20),
                  child: Row(children: [
                    const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2)),
                    const SizedBox(width: 12),
                    Expanded(
                        child: Text(isMentor
                            ? '正在深度推演解题思路与核验结论…'
                            : (session.pictures.isEmpty
                                ? '正在整理思路…'
                                : '正在读图，整理思路…'))),
                  ])),
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
            if (session.messages.isNotEmpty && !session.busy)
              Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 6,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      if (_canRevealInMentor)
                        OutlinedButton.icon(
                          onPressed: _revealInMentor,
                          icon:
                              const Icon(Icons.auto_awesome_outlined, size: 16),
                          label: const Text('查看本题导师解析'),
                        ),
                      TextButton.icon(
                          onPressed: widget.onStartWithChild,
                          icon: const Icon(Icons.child_care_outlined, size: 18),
                          label: const Text('让孩子也试试')),
                    ],
                  )),
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
    final verified = !needsConfirm &&
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
              verified ? '导师视角 · 已通过多步核验' : '导师视角 · 思路参考（建议核对原题条件）',
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
            ])));
  }
}
