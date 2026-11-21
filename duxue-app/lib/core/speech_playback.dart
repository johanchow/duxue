import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_tts/flutter_tts.dart';

/// 播放已合成的 MP3，或在服务端失败时用设备朗读原文。
abstract class SpeechPlayback {
  Stream<void> get onComplete;
  Future<void> playMp3(Uint8List bytes);
  Future<void> speak(String text, String locale);
  Future<void> stop();
  Future<void> dispose();
}

class DeviceSpeechPlayback implements SpeechPlayback {
  final AudioPlayer _player = AudioPlayer();
  FlutterTts? _tts;
  int _generation = 0;

  @override
  Stream<void> get onComplete => _player.onPlayerComplete;

  @override
  Future<void> playMp3(Uint8List bytes) async {
    final generation = ++_generation;
    await _tts?.stop();
    if (generation != _generation) return;
    await _player.stop();
    if (generation != _generation) return;
    await _player.play(BytesSource(bytes));
  }

  @override
  Future<void> speak(String text, String locale) async {
    final generation = ++_generation;
    await _player.stop();
    if (generation != _generation) return;
    final tts = _tts ??= FlutterTts();
    await tts.stop();
    await tts.setLanguage(locale);
    if (generation != _generation) return;
    await tts.speak(text);
  }

  @override
  Future<void> stop() async {
    _generation++;
    await _player.stop();
    await _tts?.stop();
  }

  @override
  Future<void> dispose() async {
    await stop();
    await _player.dispose();
  }
}
