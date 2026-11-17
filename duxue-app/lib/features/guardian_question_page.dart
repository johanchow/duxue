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
  final input = TextEditingController();
  final focus = FocusNode();
  final scroll = ScrollController();
  final messages = <Map<String, dynamic>>[];
  final pictures = <({Uint8List bytes, String extension, String? key})>[];
  String? stateToken, error, pendingQuestion;
  bool busy = false, keyboard = false, expired = false;
  int generation = 0;
  SpeechPlayback? _playback;
  SpeechPlayback get playback => _playback ??= DeviceSpeechPlayback();

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
    generation++;
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

  Future<void> _clear() async {
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
                title: const Text('重新开始问答？'),
                content: const Text('将清空本轮体验对话。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('取消')),
                  TextButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('重新开始')),
                ]));
    if (!mounted || confirmed != true) return;
    generation++;
    _playback?.stop();
    setState(() {
      messages.clear();
      pictures.clear();
      input.clear();
      stateToken = null;
      error = null;
      pendingQuestion = null;
      busy = false;
      expired = false;
    });
  }

  Future<void> _pick() async {
    if (busy || pictures.length >= 4) return;
    final epoch = generation;
    try {
      final file = await ImagePicker().pickImage(
          source: ImageSource.camera, maxWidth: 1920, imageQuality: 85);
      if (file == null) return;
      final bytes = await file.readAsBytes();
      if (!mounted || epoch != generation) return;
      final extension =
          file.name.toLowerCase().endsWith('.png') ? 'png' : 'jpg';
      setState(
          () => pictures.add((bytes: bytes, extension: extension, key: null)));
    } catch (e) {
      if (mounted && epoch == generation) {
        showMessage(context, '暂时无法拍照：${userErrorMessage(e)}');
      }
    }
  }

  Future<void> _send([String? spoken]) async {
    if (busy || expired) return;
    final content = (spoken ?? input.text).trim();
    if (content.isEmpty && pictures.isEmpty) return;
    input.clear();
    focus.unfocus();
    final epoch = generation;
    setState(() {
      busy = true;
      error = null;
      pendingQuestion = content;
    });
    _bottom();
    try {
      final api = ref.read(apiProvider);
      for (var i = 0; i < pictures.length; i++) {
        final picture = pictures[i];
        if (picture.key != null) continue;
        final key = await api.uploadGuardianExperienceImage(
            picture.bytes, picture.extension);
        if (!mounted || epoch != generation) return;
        pictures[i] =
            (bytes: picture.bytes, extension: picture.extension, key: key);
      }
      final sentPictures = [for (final picture in pictures) picture.bytes];
      final response = await api.guardianExperienceTurn(
          content: content,
          stateToken: stateToken,
          attachmentKeys: [for (final picture in pictures) picture.key!]);
      if (!mounted || epoch != generation) return;
      setState(() {
        messages.add(
            {'role': 'user', 'content': content, 'pictures': sentPictures});
        messages.add({'role': 'assistant', ...response});
        stateToken = response['state_token'] as String?;
        pictures.clear();
        input.clear();
      });
      _bottom();
    } catch (e) {
      if (!mounted || epoch != generation) return;
      setState(() {
        input.text = content;
        expired = e is DioException &&
            e.response?.data is Map &&
            (e.response!.data as Map)['detail'] is Map &&
            ((e.response!.data as Map)['detail'] as Map)['code'] ==
                'experience_expired';
        error = expired ? '本轮对话已过期，请重新开始。' : '这次没能发送成功，请重试。';
      });
    } finally {
      if (mounted && epoch == generation) {
        setState(() {
          busy = false;
          pendingQuestion = null;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Row(children: [
              const Expanded(
                  child: Text('体验 AI 伴学',
                      style: TextStyle(fontSize: 15, color: Colors.blueGrey))),
              if (messages.isNotEmpty || busy || error != null)
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
              if (messages.isEmpty && !busy && error == null) ...[
                const SizedBox(height: 24),
                const Text('先试一题，\n看看怎样一步步想明白。',
                    style: TextStyle(
                        fontSize: 26,
                        height: 1.45,
                        fontWeight: FontWeight.w600)),
                const SizedBox(height: 12),
                const Text('拍一道题，或说出你的问题。\n你可以像孩子一样追问、尝试。',
                    style: TextStyle(color: Colors.blueGrey, height: 1.6)),
                const SizedBox(height: 28),
                for (final example in const [
                  ('试一道题', '请带我理解：3/4 和 2/3 怎样比较大小？', Icons.lightbulb_outline),
                  ('问个知识点', '请用生活中的例子解释什么是比喻。', Icons.menu_book_outlined),
                  ('听听发音', '请示范 apple 的发音。', Icons.volume_up_outlined),
                ])
                  Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: OutlinedButton(
                          style: OutlinedButton.styleFrom(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 16, vertical: 15),
                              side: const BorderSide(color: Color(0xffe2e8f0)),
                              shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(14))),
                          onPressed:
                              busy || expired ? null : () => _send(example.$2),
                          child: Row(children: [
                            Icon(example.$3, size: 20),
                            const SizedBox(width: 12),
                            Expanded(child: Text(example.$1)),
                            const Icon(Icons.arrow_forward, size: 17)
                          ]))),
              ],
              for (var index = 0; index < messages.length; index++)
                _message(messages[index], index),
              if (busy || error != null)
                _message({
                  'role': 'user',
                  'content': pendingQuestion ?? input.text,
                  'pictures': [for (final picture in pictures) picture.bytes]
                }, messages.length),
              if (busy)
                Padding(
                    padding: const EdgeInsets.symmetric(vertical: 20),
                    child: Row(children: [
                      const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2)),
                      const SizedBox(width: 12),
                      Expanded(
                          child: Text(
                              pictures.isEmpty ? '正在整理思路…' : '正在读图，整理思路…')),
                    ])),
              if (error != null)
                Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Row(children: [
                      Expanded(
                          child: Text(error!,
                              style: TextStyle(
                                  color: Theme.of(context).colorScheme.error))),
                      TextButton(
                          onPressed: expired ? _clear : () => _send(),
                          child: Text(expired ? '重新开始' : '重试')),
                    ])),
              if (messages.isNotEmpty && !busy)
                Padding(
                    padding: const EdgeInsets.only(top: 24),
                    child: TextButton.icon(
                        onPressed: widget.onStartWithChild,
                        icon: const Icon(Icons.child_care_outlined, size: 18),
                        label: const Text('让孩子也试试'))),
            ])),
        if (pictures.isNotEmpty && !busy)
          SizedBox(
              height: 90,
              child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  children: [
                    for (var i = 0; i < pictures.length; i++)
                      Padding(
                          padding: const EdgeInsets.only(right: 8),
                          child: Stack(children: [
                            ClipRRect(
                                borderRadius: BorderRadius.circular(10),
                                child: Image.memory(pictures[i].bytes,
                                    width: 80, height: 80, fit: BoxFit.cover)),
                            Positioned(
                                right: 0,
                                top: 0,
                                child: IconButton.filledTonal(
                                    tooltip: '移除照片',
                                    onPressed: busy
                                        ? null
                                        : () => setState(
                                            () => pictures.removeAt(i)),
                                    icon: const Icon(Icons.close, size: 16)))
                          ])),
                  ])),
        Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
            child: keyboard
                ? Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                    IconButton(
                        tooltip: '切换语音',
                        onPressed: busy
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
                            enabled: !busy && !expired,
                            minLines: 1,
                            maxLines: 4,
                            maxLength: 2400,
                            textInputAction: TextInputAction.newline,
                            decoration: const InputDecoration(
                                hintText: '输入你的问题',
                                counterText: '',
                                isDense: true))),
                    IconButton(
                        tooltip: '拍照',
                        onPressed: busy || expired || pictures.length >= 4
                            ? null
                            : _pick,
                        icon: const Icon(Icons.camera_alt_outlined)),
                    IconButton.filled(
                        tooltip: '发送问题',
                        onPressed: busy || expired ? null : () => _send(),
                        icon: const Icon(Icons.arrow_upward, size: 20)),
                  ])
                : !widget.active
                    ? const SizedBox(height: 52)
                    : VoiceComposer(
                        baseUrl: apiBaseUrl,
                        tokens: ref.read(tokenStorageProvider),
                        telemetry: ref.read(telemetryProvider),
                        enabled: widget.active && !busy && !expired,
                        onVoiceFinal: _send,
                        onPickImage: _pick,
                        helperText:
                            pictures.isEmpty ? '轻点打字 · 按住说话' : '轻点打字，或按住说说想问什么',
                        onTap: () {
                          setState(() => keyboard = true);
                          focus.requestFocus();
                        })),
        if (pictures.isNotEmpty && !keyboard)
          TextButton(
              onPressed: busy || expired ? null : () => _send(),
              child: const Text('发送照片')),
      ]);

  Widget _message(Map<String, dynamic> message, int index) {
    final mine = message['role'] == 'user';
    final text = message['content'] as String? ?? '';
    return Align(
        alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
        child: Container(
            key: ValueKey('experience-message-$index'),
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
