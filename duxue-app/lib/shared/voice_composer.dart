import 'dart:async';

import 'package:flutter/material.dart';

import '../core/token_storage.dart';
import '../core/voice_transcription_service.dart';
import '../core/telemetry.dart';

/// A business-agnostic WeChat-style hold-to-talk control with an image action.
class VoiceComposer extends StatefulWidget {
  const VoiceComposer({
    required this.baseUrl,
    required this.tokens,
    required this.telemetry,
    required this.onVoiceFinal,
    required this.onPickImage,
    super.key,
    this.holdToTalkText = '按住说话',
    this.helperText,
    this.onTap,
    this.enabled = true,
    this.voiceFactory = VoiceTranscriptionService.new,
  });

  final String baseUrl;
  final TokenStorage tokens;
  final AppTelemetry telemetry;
  final Future<void> Function(String transcript) onVoiceFinal;
  final Future<void> Function() onPickImage;
  final String holdToTalkText;
  final String? helperText;

  /// Optional host-owned action for a light tap; recording remains long-press only.
  final VoidCallback? onTap;
  final bool enabled;
  final VoiceTranscriptionFactory voiceFactory;

  @override
  State<VoiceComposer> createState() => _VoiceComposerState();
}

class _VoiceComposerState extends State<VoiceComposer> {
  late final VoiceTranscription _voice;
  final _feedback = ValueNotifier<_RecordingFeedback?>(null);
  Timer? _limit;
  OverlayEntry? _overlay;
  var _recording = false;
  var _cancelArmed = false;

  @override
  void initState() {
    super.initState();
    _voice = widget.voiceFactory(
        baseUrl: widget.baseUrl,
        tokens: widget.tokens,
        telemetry: widget.telemetry);
  }

  @override
  void dispose() {
    _limit?.cancel();
    _removeOverlay();
    _feedback.dispose();
    unawaited(_voice.dispose());
    super.dispose();
  }

  void _showOverlay() {
    if (_overlay != null) return;
    _overlay = OverlayEntry(
        builder: (_) => ValueListenableBuilder<_RecordingFeedback?>(
            valueListenable: _feedback,
            builder: (_, feedback, __) {
              if (feedback == null) return const SizedBox.shrink();
              return IgnorePointer(
                  child: Center(
                      child: Material(
                          color: Colors.transparent,
                          child: Container(
                              width: 190,
                              padding: const EdgeInsets.all(20),
                              decoration: BoxDecoration(
                                  color: const Color(0xdd1f2937),
                                  borderRadius: BorderRadius.circular(16)),
                              child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Icon(
                                        feedback.cancelArmed
                                            ? Icons.delete_outline
                                            : Icons.keyboard_voice_rounded,
                                        color: feedback.cancelArmed
                                            ? Colors.redAccent
                                            : Colors.white,
                                        size: 42),
                                    const SizedBox(height: 12),
                                    Text(feedback.cancelArmed ? '松开取消' : '松开发送',
                                        style: const TextStyle(
                                            color: Colors.white,
                                            fontWeight: FontWeight.w700)),
                                    const SizedBox(height: 8),
                                    Text(
                                        feedback.transcript.isEmpty
                                            ? '正在听…上滑取消'
                                            : feedback.transcript,
                                        maxLines: 3,
                                        overflow: TextOverflow.ellipsis,
                                        textAlign: TextAlign.center,
                                        style: const TextStyle(
                                            color: Color(0xffd1d5db),
                                            fontSize: 13)),
                                  ])))));
            }));
    Overlay.of(context, rootOverlay: true).insert(_overlay!);
  }

  void _removeOverlay() {
    _overlay?.remove();
    _overlay = null;
  }

  void _updateFeedback({String? transcript, bool? cancelArmed}) {
    final current = _feedback.value;
    if (current == null) return;
    _feedback.value = _RecordingFeedback(
        transcript: transcript ?? current.transcript,
        cancelArmed: cancelArmed ?? current.cancelArmed);
  }

  Future<void> _start() async {
    if (_recording || !widget.enabled) return;
    try {
      await _voice.start(
          onPartial: (text) => _updateFeedback(transcript: text),
          onFinal: (text) async {
            _limit?.cancel();
            _removeOverlay();
            if (mounted) setState(() => _recording = false);
            _feedback.value = null;
            if (text.trim().isNotEmpty) await widget.onVoiceFinal(text.trim());
          },
          onError: _showError);
      if (!mounted) return;
      setState(() => _recording = true);
      _cancelArmed = false;
      _feedback.value = const _RecordingFeedback();
      _showOverlay();
      _limit = Timer(const Duration(seconds: 60), () async {
        await _stop();
        _showError('最长可录 60 秒，已结束识别');
      });
    } catch (error) {
      _showError('$error');
    }
  }

  Future<void> _stop() async {
    if (!_recording) return;
    _limit?.cancel();
    await _voice.commit();
  }

  Future<void> _cancel() async {
    if (!_recording) return;
    _limit?.cancel();
    await _voice.cancel();
    _removeOverlay();
    _feedback.value = null;
    if (mounted) setState(() => _recording = false);
  }

  void _showError(String message) {
    _limit?.cancel();
    _removeOverlay();
    _feedback.value = null;
    if (mounted) {
      setState(() => _recording = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    }
  }

  @override
  Widget build(BuildContext context) => Row(children: [
        Expanded(
            child: Semantics(
                button: true,
                label: widget.holdToTalkText,
                onTap: widget.onTap,
                child: GestureDetector(
                    onTap: widget.onTap,
                    onLongPressStart: (_) => _start(),
                    onLongPressMoveUpdate: (details) {
                      final cancel = details.offsetFromOrigin.dy < -56;
                      if (cancel != _cancelArmed) {
                        setState(() => _cancelArmed = cancel);
                        _updateFeedback(cancelArmed: cancel);
                      }
                    },
                    onLongPressEnd: (_) => _cancelArmed ? _cancel() : _stop(),
                    onLongPressCancel: _cancel,
                    child: AnimatedContainer(
                        duration: const Duration(milliseconds: 120),
                        height: 52,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                            color: _recording
                                ? (_cancelArmed
                                    ? const Color(0xffffe4e6)
                                    : const Color(0xffdbeafe))
                                : const Color(0xfff1f5f9),
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(
                                color: _recording && _cancelArmed
                                    ? Colors.redAccent
                                    : const Color(0xffcbd5e1))),
                        child: Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(_recording ? Icons.mic : Icons.mic_none,
                                  color: _cancelArmed
                                      ? Colors.redAccent
                                      : Colors.blue),
                              const SizedBox(width: 8),
                              Flexible(
                                  child: Column(
                                      mainAxisSize: MainAxisSize.min,
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                    Text(
                                        _cancelArmed
                                            ? '松开取消'
                                            : _recording
                                                ? '松开发送'
                                                : widget.holdToTalkText,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(
                                            fontWeight: FontWeight.w700)),
                                    if (!_recording &&
                                        widget.helperText != null)
                                      Text(widget.helperText!,
                                          overflow: TextOverflow.ellipsis,
                                          style: const TextStyle(
                                              fontSize: 11,
                                              color: Colors.blueGrey)),
                                  ])),
                            ]))))),
        const SizedBox(width: 10),
        SizedBox(
            width: 64,
            height: 52,
            child: OutlinedButton(
                onPressed:
                    _recording || !widget.enabled ? null : widget.onPickImage,
                style: OutlinedButton.styleFrom(padding: EdgeInsets.zero),
                child: const Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.image_outlined, size: 20),
                      Text('图片', style: TextStyle(fontSize: 11)),
                    ]))),
      ]);
}

class _RecordingFeedback {
  const _RecordingFeedback({this.transcript = '', this.cancelArmed = false});
  final String transcript;
  final bool cancelArmed;
}
