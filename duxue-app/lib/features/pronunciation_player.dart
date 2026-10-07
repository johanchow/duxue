import 'dart:typed_data';

import 'package:duxue_app/core/speech_playback.dart';
import 'package:duxue_app/shared/app_ui.dart';
import 'package:flutter/material.dart';

class PronunciationLessonCard extends StatefulWidget {
  const PronunciationLessonCard({
    required this.lesson,
    required this.loadSpeech,
    required this.playback,
    super.key,
  });

  final Map<String, dynamic> lesson;
  final Future<Uint8List> Function(String speechRef, double rate) loadSpeech;
  final SpeechPlayback playback;

  @override
  State<PronunciationLessonCard> createState() => _PronunciationLessonCardState();
}

class _PronunciationLessonCardState extends State<PronunciationLessonCard> {
  static const _rates = <double>[0.5, 0.75, 1.0];
  double _rate = 1.0;
  bool _loading = false;
  String? _status;

  List<double> get _allowedRates {
    final raw = widget.lesson['supported_rates'];
    if (raw is! List || raw.isEmpty) return _rates;
    final parsed = <double>[
      for (final item in raw)
        if (item is num && _rates.contains(item.toDouble())) item.toDouble(),
    ];
    return parsed.isEmpty ? _rates : parsed;
  }

  @override
  void initState() {
    super.initState();
    final allowed = _allowedRates;
    _rate = allowed.contains(1.0) ? 1.0 : allowed.first;
  }

  @override
  void dispose() {
    widget.playback.stop();
    super.dispose();
  }

  Future<void> _play() async {
    final speechRef = widget.lesson['speech_ref'] as String?;
    final source = widget.lesson['source_text'] as String? ?? '';
    final locale = widget.lesson['locale'] as String? ?? 'en-US';
    if (speechRef == null || speechRef.isEmpty || source.isEmpty) return;
    setState(() {
      _loading = true;
      _status = null;
    });
    try {
      final bytes = await widget.loadSpeech(speechRef, _rate);
      if (!mounted) return;
      await widget.playback.playMp3(bytes);
      if (!mounted) return;
      setState(() => _status = '正在播放');
    } catch (_) {
      if (!mounted) return;
      try {
        await widget.playback.speak(source, locale);
        if (!mounted) return;
        setState(() => _status = '服务端暂时读不了，已改用手机朗读');
      } catch (_) {
        if (!mounted) return;
        setState(() => _status = '暂时读不出来');
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final lesson = widget.lesson;
    final notes = (lesson['notes'] as List? ?? const [])
        .whereType<Map>()
        .map((note) => Map<String, dynamic>.from(note));
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(lesson['introduction'] as String? ?? '听一听这句怎么读',
              style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          Text(lesson['source_text'] as String? ?? '',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
          if ((lesson['reading_guide'] as String?)?.isNotEmpty == true) ...[
            const SizedBox(height: 6),
            Text(lesson['reading_guide'] as String,
                style: const TextStyle(color: Colors.blueGrey)),
          ],
          for (final note in notes)
            if ((note['explanation'] as String?)?.isNotEmpty == true)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('• ${note['explanation']}',
                    style: const TextStyle(fontSize: 13)),
              ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            children: [
              for (final rate in _allowedRates)
                ChoiceChip(
                  label: Text(rate == rate.roundToDouble()
                      ? '${rate.toStringAsFixed(1)}x'
                      : '${rate}x'),
                  selected: _rate == rate,
                  onSelected: _loading
                      ? null
                      : (_) => setState(() => _rate = rate),
                ),
            ],
          ),
          const SizedBox(height: 8),
          FilledButton.icon(
            onPressed: _loading ? null : _play,
            icon: Icon(_loading ? Icons.hourglass_top : Icons.volume_up),
            label: Text(_loading ? '准备朗读' : '播放'),
          ),
          if (_status != null) ...[
            const SizedBox(height: 6),
            Text(_status!, style: const TextStyle(fontSize: 12)),
          ],
        ],
      ),
    );
  }
}
