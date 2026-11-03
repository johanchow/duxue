import 'dart:async';

import 'package:duxue_app/core/telemetry.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/shared/input_mode_composer.dart';
import 'package:duxue_app/shared/voice_composer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget composer({
  required Future<void> Function(String) onSubmit,
  required Future<void> Function(String) onPickImage,
}) =>
    MaterialApp(
        home: Scaffold(
            body: Padding(
      padding: const EdgeInsets.all(16),
      child: InputModeComposer(
        hintText: '传递作业或留言',
        onSubmit: onSubmit,
        onPickImage: onPickImage,
        voiceComposer: VoiceComposer(
          baseUrl: 'http://localhost',
          tokens: const TokenStorage(),
          telemetry: AppTelemetry(
            config: const TelemetryConfig(
                enabled: false, relayUrl: '', sampleRate: 0),
            accessToken: () async => null,
          ),
          onVoiceFinal: onSubmit,
          onPickImage: () => onPickImage(''),
        ),
      ),
    )));

void main() {
  testWidgets(
      'photo receives text draft and cancelling keeps it on a narrow screen',
      (tester) async {
    tester.view.physicalSize = const Size(320, 700);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    String? photoDraft;
    var submissions = 0;
    await tester.pumpWidget(composer(
      onSubmit: (_) async => submissions++,
      onPickImage: (text) async => photoDraft = text,
    ));
    await tester.tap(find.byTooltip('切换到文字输入'));
    await tester.pumpAndSettle();
    await tester.testTextInput.receiveAction(TextInputAction.send);
    expect(submissions, 0);
    await tester.enterText(find.byType(TextField), '数学练习册');
    await tester.tap(find.byTooltip('拍照'));
    await tester.pumpAndSettle();
    expect(photoDraft, '数学练习册');
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '数学练习册');
    expect(tester.takeException(), isNull);
  });

  testWidgets('keyboard send waits for host and prevents duplicate submissions',
      (tester) async {
    final gate = Completer<void>();
    final submissions = <String>[];
    await tester.pumpWidget(composer(
      onSubmit: (text) async {
        submissions.add(text);
        await gate.future;
      },
      onPickImage: (_) async {},
    ));
    await tester.tap(find.byTooltip('切换到文字输入'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '  明天交练习册  ');
    await tester.testTextInput.receiveAction(TextInputAction.send);
    await tester.pump();
    await tester.tap(find.byTooltip('发送'));
    expect(submissions, ['明天交练习册']);
    expect(tester.widget<TextField>(find.byType(TextField)).enabled, isFalse);
    gate.complete();
    await tester.pumpAndSettle();
    expect(
        tester.widget<TextField>(find.byType(TextField)).controller!.text, '');
  });
}
