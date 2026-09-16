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
  Future<Map<String, dynamic>> companionTurn({
    required String content,
    required String? threadId,
    required int? expectedThreadVersion,
    bool planningConfirm = false,
    List<String> attachmentKeys = const [],
  }) async =>
      {
        'thread_id': threadId ?? 'thread-1',
        'thread_version': (expectedThreadVersion ?? 0) + 2,
        'interaction': {
          'model_guidance': '已整理为今天的草稿。',
          'items': [
            {'title': '整理错题', 'planned_minutes': 20, 'new_task': true},
          ],
        },
      };

  @override
  Future<List<dynamic>> companionMessages(String threadId) async => const [];
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

  testWidgets('V3 home opens the complete plan timeline and task context',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(_WardHomeApi())],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    expect(find.text('已确认 · 今日计划'), findsOneWidget);
    expect(find.text('AI 伙伴'), findsNothing);
    expect(find.byTooltip('打开读学对话'), findsNothing);
    await tester.tap(find.text('说出你的任何想法、问题、安排'));
    await tester.pumpAndSettle();
    expect(find.text('你先说；我记录并检查冲突，确认后才生效。'), findsOneWidget);
    expect(find.text('说出你的任何想法、问题、安排'), findsOneWidget);

    await tester.tap(find.byTooltip('关闭'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('全部'));
    await tester.pumpAndSettle();
    expect(find.text('今日计划'), findsOneWidget);
    expect(find.text('已确认 · 共 1 项 · 你说了算'), findsOneWidget);

    await tester.tap(find.text('数学练习册').last);
    await tester.pumpAndSettle();
    expect(find.text('语境：关于「数学练习册」——按住下方再说。'), findsOneWidget);
  });

  testWidgets('V3 home removes a task-pool item locally when swiped',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(_WardHomeApi())],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    await tester.drag(find.text('观察蚂蚁路线'), const Offset(-500, 0));
    await tester.pumpAndSettle();
    expect(find.text('观察蚂蚁路线'), findsNothing);
    expect(find.text('今天没有待定项了。想加任务，走下方统一入口。'), findsOneWidget);
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
                    config: const TelemetryConfig(
                        enabled: false, relayUrl: '', sampleRate: 0),
                    accessToken: () async => null),
                voiceFactory: (
                        {required baseUrl,
                        required tokens,
                        required telemetry}) =>
                    voice,
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

  testWidgets('a light composer tap invokes only the host callback',
      (tester) async {
    var tapped = false;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: VoiceComposer(
                baseUrl: 'http://localhost',
                tokens: const TokenStorage(),
                telemetry: AppTelemetry(
                    config: const TelemetryConfig(
                        enabled: false, relayUrl: '', sampleRate: 0),
                    accessToken: () async => null),
                onTap: () => tapped = true,
                onVoiceFinal: (_) async {},
                onPickImage: () async {}))));

    await tester.tap(find.text('按住说话'));
    expect(tapped, isTrue);
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
                    config: const TelemetryConfig(
                        enabled: false, relayUrl: '', sampleRate: 0),
                    accessToken: () async => null),
                voiceFactory: (
                        {required baseUrl,
                        required tokens,
                        required telemetry}) =>
                    voice,
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
