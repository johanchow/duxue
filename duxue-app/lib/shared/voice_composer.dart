import 'dart:async';

import 'package:flutter/material.dart';

import '../core/token_storage.dart';
import '../core/voice_transcription_service.dart';

/// Reusable text, optional media and hold-to-talk composer.
class VoiceComposer extends StatefulWidget {
  const VoiceComposer({
    required this.controller,
    required this.baseUrl,
    required this.tokens,
    required this.onSend,
    super.key,
    this.hintText = '输入内容',
    this.allowMediaUpload = false,
    this.onPickMedia,
    this.enabled = true,
  });

  final TextEditingController controller;
  final String baseUrl;
  final TokenStorage tokens;
  final Future<void> Function(String text) onSend;
  final String hintText;
  final bool allowMediaUpload;
  final Future<void> Function()? onPickMedia;
  final bool enabled;

  @override
  State<VoiceComposer> createState() => _VoiceComposerState();
}

class _VoiceComposerState extends State<VoiceComposer> {
  late final VoiceTranscriptionService _voice;
  Timer? _limit;
  var _recording = false;
  var _sending = false;

  @override
  void initState() {
    super.initState();
    _voice = VoiceTranscriptionService(
        baseUrl: widget.baseUrl, tokens: widget.tokens);
  }

  @override
  void dispose() {
    _limit?.cancel();
    unawaited(_voice.dispose());
    super.dispose();
  }

  void _replaceText(String text) {
    widget.controller.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }

  Future<void> _start() async {
    if (_recording || _sending || !widget.enabled) return;
    try {
      await _voice.start(
        onPartial: (text) {
          if (mounted) setState(() => _replaceText(text));
        },
        onFinal: (text) {
          if (mounted) {
            setState(() {
              _recording = false;
              _replaceText(text);
            });
          }
          _limit?.cancel();
        },
        onError: (message) {
          if (mounted) {
            setState(() => _recording = false);
            ScaffoldMessenger.of(context)
                .showSnackBar(SnackBar(content: Text(message)));
          }
          _limit?.cancel();
        },
      );
      if (!mounted) return;
      setState(() => _recording = true);
      _limit = Timer(const Duration(seconds: 60), () async {
        await _stop();
        if (mounted) {
          ScaffoldMessenger.of(context)
              .showSnackBar(const SnackBar(content: Text('最长可录 60 秒，已结束识别')));
        }
      });
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  Future<void> _stop() async {
    if (!_recording) return;
    _limit?.cancel();
    if (mounted) setState(() => _recording = false);
    await _voice.commit();
  }

  Future<void> _cancel() async {
    if (!_recording) return;
    _limit?.cancel();
    if (mounted) setState(() => _recording = false);
    await _voice.cancel();
  }

  Future<void> _send() async {
    final text = widget.controller.text.trim();
    if (text.isEmpty || _recording || _sending || !widget.enabled) return;
    setState(() => _sending = true);
    try {
      await widget.onSend(text);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) => Row(children: [
        if (widget.allowMediaUpload)
          IconButton(
              onPressed: !_recording && !_sending && widget.enabled
                  ? widget.onPickMedia
                  : null,
              icon: const Icon(Icons.add_circle_outline),
              tooltip: '添加媒体'),
        Expanded(
            child: AbsorbPointer(
                absorbing: _recording,
                child: TextField(
                    controller: widget.controller,
                    minLines: 1,
                    maxLines: 4,
                    decoration: InputDecoration(
                        isDense: true,
                        hintText:
                            _recording ? '正在识别，松开后可编辑' : widget.hintText)))),
        GestureDetector(
            onLongPressStart: (_) => _start(),
            onLongPressEnd: (_) => _stop(),
            onLongPressCancel: _cancel,
            child: SizedBox(
                width: 44,
                height: 44,
                child: Icon(_recording ? Icons.mic : Icons.mic_none,
                    color: _recording ? Colors.red : null))),
        IconButton(
            onPressed: _send,
            icon: _sending
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.arrow_upward),
            tooltip: '发送'),
      ]);
}
