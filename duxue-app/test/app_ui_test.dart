import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/core/voice_transcription_service.dart';
import 'package:duxue_app/core/telemetry.dart';
import 'package:duxue_app/features/day_story_pages.dart';
import 'package:duxue_app/providers.dart';
import 'package:duxue_app/shared/voice_composer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _WardHomeApi extends ApiClient {
  _WardHomeApi()
      : super(baseUrl: 'http://localhost', tokens: const TokenStorage());
  var startedAssignment = false;
  var confirmedPlanIntake = false;

  @override
  Future<List<dynamic>> assignments(String wardId) async => [
        {
          'id': 'pool-1',
          'title': '观察蚂蚁路线',
          'details': '兴趣探索',
          'status': 'open'
        },
      ];

  @override
  Future<Map<String, dynamic>> plan(String wardId, DateTime day) async => {
        'status': 'confirmed',
        'items': [
          {
            'id': 'plan-1',
            'assignment_id': 'planned-1',
            'title': '数学练习册',
            'planned_minutes': 30,
            'status': 'pending',
            'session': null,
          },
        ],
      };

  @override
  Future<Map<String, dynamic>> wardProfile() async => {
        'id': 'ward-1',
        'display_name': '小读',
        'guardians': [
          {'id': 'guardian-1', 'name': '林妈妈'},
        ],
      };

  @override
  Future<Map<String, dynamic>> startAssignmentSession(
      String assignmentId) async {
    startedAssignment = true;
    return {'id': 'session-1', 'status': 'active', 'active_seconds': 0};
  }

  @override
  Future<Map<String, dynamic>> respondToPlanIntake(String wardId, DateTime day,
          {required String content,
          required List<Map<String, dynamic>> draftItems,
          required List<String> attachmentKeys}) async =>
      {
        'assistant_text': '已整理为今天的草稿。',
        'items': [
          {
            'title': '整理错题',
            'planned_minutes': 20,
            'new_task': true,
          },
        ],
        'ready_to_confirm': true,
      };

  @override
  Future<void> confirmPlanIntake(String wardId, DateTime day,
      List<Map<String, dynamic>> items, List<String> attachmentKeys) async {
    confirmedPlanIntake = true;
  }
}

class _FakeVoice implements VoiceTranscription {
  late TranscriptHandler onPartial;
  late TranscriptHandler onFinal;
  late VoiceErrorHandler onError;
  var cancelled = false;

  @override
  Future<void> start(
      {required TranscriptHandler onPartial,
      required TranscriptHandler onFinal,
      required VoiceErrorHandler onError}) async {
    this.onPartial = onPartial;
    this.onFinal = onFinal;
    this.onError = onError;
  }

  @override
  Future<void> cancel() async => cancelled = true;

  @override
  Future<void> commit() async => onFinal('今天整理错题');

  @override
  Future<void> dispose() async {}
}

void main() {
  testWidgets('task-pool item requires confirmation before it starts',
      (tester) async {
    final api = _WardHomeApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('观察蚂蚁路线'));
    await tester.pumpAndSettle();
    expect(find.text('开始学习？'), findsOneWidget);
    expect(api.startedAssignment, isFalse);

    await tester.tap(find.text('确认开始'));
    await tester.pumpAndSettle();
    expect(api.startedAssignment, isTrue);
  });

  testWidgets(
      'holding talk sends its final transcript and image invokes callback',
      (tester) async {
    final voice = _FakeVoice();
    String? transcript;
    var imagePressed = false;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: VoiceComposer(
                baseUrl: 'http://localhost',
                tokens: const TokenStorage(),
                telemetry: AppTelemetry(
                    config: const TelemetryConfig(enabled: false, relayUrl: '', sampleRate: 0),
                    accessToken: () async => null),
                voiceFactory: ({required baseUrl, required tokens, required telemetry}) => voice,
                onVoiceFinal: (value) async => transcript = value,
                onPickImage: () async => imagePressed = true))));

    final gesture =
        await tester.startGesture(tester.getCenter(find.text('按住说话')));
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.up();
    await tester.pumpAndSettle();
    await tester.tap(find.text('图片'));

    expect(transcript, '今天整理错题');
    expect(imagePressed, isTrue);
  });

  testWidgets('sliding up while holding talk cancels without sending',
      (tester) async {
    final voice = _FakeVoice();
    String? transcript;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: VoiceComposer(
                baseUrl: 'http://localhost',
                tokens: const TokenStorage(),
                telemetry: AppTelemetry(
                    config: const TelemetryConfig(enabled: false, relayUrl: '', sampleRate: 0),
                    accessToken: () async => null),
                voiceFactory: ({required baseUrl, required tokens, required telemetry}) => voice,
                onVoiceFinal: (value) async => transcript = value,
                onPickImage: () async {}))));

    final gesture =
        await tester.startGesture(tester.getCenter(find.text('按住说话')));
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.moveBy(const Offset(0, -80));
    await gesture.up();
    await tester.pumpAndSettle();

    expect(voice.cancelled, isTrue);
    expect(transcript, isNull);
  });
}
