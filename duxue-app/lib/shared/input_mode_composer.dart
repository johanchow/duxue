import 'package:flutter/material.dart';

import '../core/user_error_message.dart';
import 'voice_composer.dart';

/// Adds a keyboard mode around the existing hold-to-talk composer.
class InputModeComposer extends StatefulWidget {
  const InputModeComposer({
    required this.voiceComposer,
    required this.hintText,
    required this.onSubmit,
    required this.onPickImage,
    super.key,
  });

  final VoiceComposer voiceComposer;
  final String hintText;
  final Future<void> Function(String text) onSubmit;
  final Future<void> Function(String draft) onPickImage;

  @override
  State<InputModeComposer> createState() => _InputModeComposerState();
}

class _InputModeComposerState extends State<InputModeComposer> {
  final _text = TextEditingController();
  final _focus = FocusNode();
  bool _voiceMode = true;
  bool _busy = false;

  @override
  void dispose() {
    _text.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _submit({bool image = false}) async {
    final text = _text.text.trim();
    if (_busy || (!image && text.isEmpty)) return;
    _focus.unfocus();
    setState(() => _busy = true);
    try {
      if (image) {
        await widget.onPickImage(text);
      } else {
        await widget.onSubmit(text);
        if (mounted) _text.clear();
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(userErrorMessage(error))),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Row(children: [
        IconButton(
          tooltip: _voiceMode ? '切换到文字输入' : '切换到语音输入',
          iconSize: 22,
          padding: EdgeInsets.zero,
          constraints: const BoxConstraints.tightFor(width: 32, height: 44),
          style: IconButton.styleFrom(
            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
          ),
          icon: Icon(_voiceMode ? Icons.keyboard_outlined : Icons.mic_none),
          onPressed: _busy
              ? null
              : () {
                  _focus.unfocus();
                  setState(() => _voiceMode = !_voiceMode);
                  if (!_voiceMode) _focus.requestFocus();
                },
        ),
        const SizedBox(width: 4),
        Expanded(
          child: _voiceMode
              ? widget.voiceComposer
              : Row(children: [
                  Expanded(
                    child: TextField(
                      controller: _text,
                      focusNode: _focus,
                      enabled: !_busy,
                      minLines: 1,
                      maxLines: 3,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _submit(),
                      onChanged: (_) => setState(() {}),
                      decoration: InputDecoration(
                        hintText: widget.hintText,
                        filled: true,
                        fillColor: const Color(0xfff1f5f9),
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 14),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  SizedBox(
                    width: 64,
                    height: 52,
                    child: Tooltip(
                      message: '拍照',
                      child: OutlinedButton(
                        onPressed: _busy ? null : () => _submit(image: true),
                        style:
                            OutlinedButton.styleFrom(padding: EdgeInsets.zero),
                        child: const Icon(Icons.camera_alt_outlined, size: 20),
                      ),
                    ),
                  ),
                  if (_text.text.trim().isNotEmpty)
                    IconButton.filled(
                      tooltip: '发送',
                      onPressed: _busy ? null : () => _submit(),
                      icon: const Icon(Icons.arrow_upward),
                    ),
                ]),
        ),
      ]);
}
