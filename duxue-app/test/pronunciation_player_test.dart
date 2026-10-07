import 'dart:typed_data';

import 'package:duxue_app/core/speech_playback.dart';
import 'package:duxue_app/features/pronunciation_player.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _FakePlayback implements SpeechPlayback {
  final played = <Uint8List>[];
  final spoken = <({String text, String locale})>[];
  int stops = 0;

  @override
  Future<void> playMp3(Uint8List bytes) async {
    played.add(bytes);
  }

  @override
  Future<void> speak(String text, String locale) async {
    spoken.add((text: text, locale: locale));
  }

  @override
  Future<void> stop() async {
    stops += 1;
  }

  @override
  Future<void> dispose() async {}
}

void main() {
  const lesson = {
    'source_text': 'apple',
    'locale': 'en-US',
    'introduction': '先听这个词。',
    'reading_guide': '重音在最前面。',
    'notes': [
      {'explanation': 'a 要轻。'}
    ],
    'speech_ref': 'lesson-1',
    'supported_rates': [0.5, 0.75, 1.0],
  };

  testWidgets('player waits for a tap and uses the selected rate', (tester) async {
    final playback = _FakePlayback();
    final rates = <double>[];
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: PronunciationLessonCard(
          lesson: lesson,
          playback: playback,
          loadSpeech: (ref, rate) async {
            rates.add(rate);
            return Uint8List.fromList([1, 2, 3]);
          },
        ),
      ),
    ));

    expect(find.text('apple'), findsOneWidget);
    expect(playback.played, isEmpty);
    await tester.tap(find.text('0.75x'));
    await tester.pump();
    await tester.tap(find.text('播放'));
    await tester.pumpAndSettle();

    expect(rates, [0.75]);
    expect(playback.played.single, Uint8List.fromList([1, 2, 3]));
    expect(find.text('正在播放'), findsOneWidget);
  });

  testWidgets('server speech failure falls back to device speech', (tester) async {
    final playback = _FakePlayback();
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: PronunciationLessonCard(
          lesson: lesson,
          playback: playback,
          loadSpeech: (_, __) async => throw StateError('tts'),
        ),
      ),
    ));

    await tester.tap(find.text('播放'));
    await tester.pumpAndSettle();

    expect(playback.played, isEmpty);
    expect(playback.spoken.single.text, 'apple');
    expect(playback.spoken.single.locale, 'en-US');
    expect(find.text('服务端暂时读不了，已改用手机朗读'), findsOneWidget);
  });
}
