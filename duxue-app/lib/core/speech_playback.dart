import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_tts/flutter_tts.dart';

/// 播放已合成的 MP3，或在服务端失败时用设备朗读原文。
abstract class SpeechPlayback {
  Future<void> playMp3(Uint8List bytes);
  Future<void> speak(String text, String locale);
  Future<void> stop();
  Future<void> dispose();
}

class DeviceSpeechPlayback implements SpeechPlayback {
  DeviceSpeechPlayback()
      : _player = AudioPlayer(),
        _tts = FlutterTts();

  final AudioPlayer _player;
  final FlutterTts _tts;

  @override
  Future<void> playMp3(Uint8List bytes) async {
    await _tts.stop();
    await _player.stop();
    await _player.play(BytesSource(bytes));
  }

  @override
  Future<void> speak(String text, String locale) async {
    await _player.stop();
    await _tts.stop();
    await _tts.setLanguage(locale);
    await _tts.speak(text);
  }

  @override
  Future<void> stop() async {
    await _player.stop();
    await _tts.stop();
  }

  @override
  Future<void> dispose() async {
    await stop();
    await _player.dispose();
  }
}
