import 'dart:async';
import 'dart:typed_data';

import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/models.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/core/voice_transcription_service.dart';
import 'package:duxue_app/core/speech_playback.dart';
import 'package:duxue_app/core/telemetry.dart';
import 'package:duxue_app/features/day_story_pages.dart';
import 'package:duxue_app/features/login_page.dart';
import 'package:duxue_app/features/ward_pages.dart';
import 'package:duxue_app/providers.dart';
import 'package:duxue_app/shared/voice_composer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

class _FakePlayback implements SpeechPlayback {
  final played = <Uint8List>[];

  @override
  Future<void> playMp3(Uint8List bytes) async {
    played.add(bytes);
  }

  @override
  Future<void> speak(String text, String locale) async {}

  @override
  Future<void> stop() async {}

  @override
  Future<void> dispose() async {}
}

class _WardHomeApi extends ApiClient {
  _WardHomeApi()
      : super(baseUrl: 'http://localhost', tokens: const TokenStorage());
  var startedAssignment = false;
  String? lastRouteHint;
  String? lastTutoringIntent;
  final speechRates = <double>[];
  String? startedPlanItem;
  String? pausedSessionId;
  String? finishedSessionId;
  final deleted = <String>[];
  final turns = <({String content, List<String> attachmentKeys})>[];

  @override
  Future<void> ensureValidAccess() async {}

  @override
  Future<void> deleteAssignment(String wardId, String assignmentId) async {
    deleted.add(assignmentId);
  }

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
  Future<Map<String, dynamic>> startSession(String itemId) async {
    startedPlanItem = itemId;
    return {'id': 'session-plan', 'status': 'active', 'active_seconds': 0};
  }

  @override
  Future<Map<String, dynamic>> pauseSession(
      String sessionId, int seconds) async {
    pausedSessionId = sessionId;
    return {
      'id': sessionId,
      'status': 'paused',
      'active_seconds': seconds,
    };
  }

  @override
  Future<void> finishSession(String sessionId, int seconds) async {
    finishedSessionId = sessionId;
  }

  @override
  Future<Map<String, dynamic>> companionTurn({
    required String content,
    required String? threadId,
    required int? expectedThreadVersion,
    String? routeHint,
    String? tutoringIntent,
    Map<String, dynamic>? structuredCommand,
    List<String> attachmentKeys = const [],
  }) async {
    lastRouteHint = routeHint;
    lastTutoringIntent = tutoringIntent;
    turns.add((
      content: content,
      attachmentKeys: List<String>.from(attachmentKeys),
    ));
    if (tutoringIntent == 'pronunciation' || content == 'apple') {
      return {
        'thread_id': threadId ?? 'thread-1',
        'thread_version': (expectedThreadVersion ?? 0) + 2,
        'interaction': {
          'protocol': 'companion-interaction.v1',
          'kind': 'pronunciation_lesson',
          'parts': [
            {'type': 'text', 'text': '先听这个词。'},
          ],
          'object_ref': {
            'context': 'study',
            'object_id': 'lesson-1',
          },
        },
      };
    }
    if (content == 'start also') {
      return {
        'thread_id': threadId ?? 'thread-1',
        'thread_version': (expectedThreadVersion ?? 0) + 2,
        'interaction': {
          'protocol': 'companion-interaction.v1',
          'kind': 'pronunciation_lesson',
          'content': 'start 是开始，also 是也。',
          'parts': [
            {'type': 'text', 'text': 'start 是开始，also 是也。'},
          ],
          'object_ref': {
            'context': 'study',
            'object_id': 'lesson-multi',
          },
        },
      };
    }
    if (content.contains('水循环')) {
      return {
        'thread_id': threadId ?? 'thread-1',
        'thread_version': (expectedThreadVersion ?? 0) + 2,
        'interaction': {
          'protocol': 'companion-interaction.v1',
          'kind': 'text_visual',
          'content': '水先蒸发，再凝结，最后降下来。',
          'parts': [
            {'type': 'text', 'text': '水先蒸发，再凝结，最后降下来。'},
            {
              'type': 'visual',
              'visual': {
                'kind': 'steps',
                'alt': '水循环三步',
                'steps': [
                  {'label': '蒸发'},
                  {'label': '凝结'},
                  {'label': '降水'},
                ],
              },
            },
          ],
          'actions': [],
        },
      };
    }
    if (structuredCommand != null) {
      return {
        'thread_id': threadId ?? 'thread-1',
        'thread_version': (expectedThreadVersion ?? 0) + 2,
        'run_status': 'closed',
        'interaction': {'status': 'confirmed'},
      };
    }
    return {
      'thread_id': threadId ?? 'thread-1',
      'thread_version': (expectedThreadVersion ?? 0) + 2,
      'interaction': {
        'protocol': 'companion-interaction.v1',
        'kind': 'plan_confirm_list',
        'parts': [
          {'type': 'text', 'text': '已整理为今天的草稿。'},
        ],
        'object_ref': {
          'context': 'planning',
          'object_id': 'draft-1',
        },
        'actions': [
          {
            'id': 'plan:run:1:draft-1:2',
            'command': 'confirm_plan',
            'enabled': true
          },
        ],
      },
    };
  }

  @override
  Future<Map<String, dynamic>> companionPlanDraft(String draftId) async => {
        'draft_id': draftId,
        'object_version': 2,
        'items': [
          {'title': '整理错题', 'planned_minutes': 20},
        ],
        'confirm_enabled': true,
      };

  @override
  Future<Map<String, dynamic>> currentStartCue() async => {'status': 'none'};

  @override
  Future<Map<String, dynamic>> pronunciationLesson(String lessonRef) async =>
      lessonRef == 'lesson-multi'
          ? {
              'id': lessonRef,
              'source_text': 'start',
              'locale': 'en-US',
              'introduction': 'start（开始）',
              'speech_ref': lessonRef,
              'supported_rates': [0.5, 0.75, 1.0],
              'lessons': [
                {
                  'lesson_ref': lessonRef,
                  'source_text': 'start',
                  'locale': 'en-US',
                  'introduction': 'start（开始）',
                  'speech_ref': lessonRef,
                  'supported_rates': [0.5, 0.75, 1.0],
                },
                {
                  'lesson_ref': '$lessonRef:1',
                  'source_text': 'also',
                  'locale': 'en-US',
                  'introduction': 'also（也）',
                  'speech_ref': '$lessonRef:1',
                  'supported_rates': [0.5, 0.75, 1.0],
                },
              ],
            }
          : {
              'id': lessonRef,
              'source_text': 'apple',
              'locale': 'en-US',
              'introduction': '先听这个词。',
              'speech_ref': lessonRef,
              'supported_rates': [0.5, 0.75, 1.0],
            };

  @override
  Future<Uint8List> pronunciationSpeech(String lessonRef, double rate) async {
    speechRates.add(rate);
    return Uint8List.fromList([9, 9, 9]);
  }

  Map<String, dynamic>? currentTranscriptOverride;
  final Map<String, Map<String, dynamic>> threadTranscriptOverrides = {};
  final List<({String threadId, int? beforeThreadVersion, int limit})>
      transcriptCalls = [];

  @override
  Future<Map<String, dynamic>> currentCompanionMessages({
    int? beforeThreadVersion,
    int limit = 50,
  }) async {
    if (currentTranscriptOverride != null) {
      return currentTranscriptOverride!;
    }
    return {
      'thread_id': null,
      'thread_version': 0,
      'messages': const <Map<String, dynamic>>[],
      'next_before_thread_version': null,
      'previous_thread_id': null,
    };
  }

  @override
  Future<Map<String, dynamic>> companionMessages(
    String threadId, {
    int? beforeThreadVersion,
    int limit = 50,
  }) async {
    transcriptCalls.add((
      threadId: threadId,
      beforeThreadVersion: beforeThreadVersion,
      limit: limit,
    ));
    final key = '$threadId:${beforeThreadVersion ?? "latest"}';
    if (threadTranscriptOverrides.containsKey(key)) {
      return threadTranscriptOverrides[key]!;
    }
    return {
      'thread_id': threadId,
      'thread_version': 1,
      'messages': [
        for (final turn in turns) ...[
          {
            'author_type': 'ward',
            'content': turn.content,
            'attachment_refs': turn.attachmentKeys,
          },
          if (turn.content.contains('水循环'))
            {
              'author_type': 'companion',
              'content': '水先蒸发，再凝结，最后降下来。',
              'attachment_refs': const <String>[],
              'interaction_ref': {
                'kind': 'text_visual',
                'parts': [
                  {
                    'type': 'visual',
                    'visual': {
                      'kind': 'steps',
                      'alt': '水循环三步',
                      'steps': [
                        {'label': '蒸发'},
                        {'label': '凝结'},
                        {'label': '降水'},
                      ],
                    },
                  },
                ],
              },
            },
        ],
      ],
    };
  }

  @override
  Future<String> uploadCompanionAttachment(
          Uint8List bytes, String extension) async =>
      'ward/ward-1/companion/test.$extension';

  final storedWards = <Ward>[];
  String? boundCode;
  String? invitedWardId;

  @override
  Future<List<Ward>> wards() async => List<Ward>.from(storedWards);

  @override
  Future<Ward> createWard(String name, String gradeStage) async {
    final created = Ward(
      id: 'ward-new',
      displayName: name,
      gradeStage: gradeStage,
      notes: null,
      analysisProfileId: null,
    );
    storedWards.add(created);
    return created;
  }

  @override
  Future<Map<String, dynamic>> wardInvite(String wardId) async {
    invitedWardId = wardId;
    return {'ward_id': wardId, 'invite_code': '654321'};
  }

  @override
  Future<String> bindWard(String code) async {
    boundCode = code;
    return 'ward-1';
  }
}

const _tinyPng = <int>[
  137,
  80,
  78,
  71,
  13,
  10,
  26,
  10,
  0,
  0,
  0,
  13,
  73,
  72,
  68,
  82,
  0,
  0,
  0,
  1,
  0,
  0,
  0,
  1,
  8,
  2,
  0,
  0,
  0,
  144,
  119,
  83,
  222,
  0,
  0,
  0,
  11,
  73,
  68,
  65,
  84,
  120,
  156,
  99,
  96,
  0,
  2,
  0,
  0,
  5,
  0,
  1,
  122,
  94,
  171,
  63,
  0,
  0,
  0,
  0,
  73,
  69,
  78,
  68,
  174,
  66,
  96,
  130,
];

class _ActiveTaskApi extends _WardHomeApi {
  Completer<void>? pauseGate;

  @override
  Future<List<dynamic>> assignments(String wardId) async => [
        {
          'id': 'pool-1',
          'title': '观察蚂蚁路线',
          'details': '兴趣探索',
          'status': 'pool',
          'session': {
            'id': 'session-live',
            'status': pausedSessionId == null ? 'active' : 'paused',
            'active_seconds': 120,
          },
        },
      ];

  @override
  Future<Map<String, dynamic>> pauseSession(
      String sessionId, int seconds) async {
    pausedSessionId = sessionId;
    final gate = pauseGate;
    if (gate != null) await gate.future;
    return {
      'id': sessionId,
      'status': 'paused',
      'active_seconds': seconds,
    };
  }

  @override
  Future<Map<String, dynamic>> plan(String wardId, DateTime day) async => {
        'status': 'confirmed',
        'items': const [],
      };
}

class _PausedTaskApi extends _WardHomeApi {
  Completer<void>? resumeGate;
  var resumed = false;

  @override
  Future<List<dynamic>> assignments(String wardId) async => [
        {
          'id': 'pool-1',
          'title': '观察蚂蚁路线',
          'details': '兴趣探索',
          'status': 'pool',
          'session': {
            'id': 'session-live',
            'status': resumed ? 'active' : 'paused',
            'active_seconds': 30,
          },
        },
      ];

  @override
  Future<Map<String, dynamic>> plan(String wardId, DateTime day) async => {
        'status': 'confirmed',
        'items': const [],
      };

  @override
  Future<Map<String, dynamic>> resumeSession(String sessionId) async {
    resumed = true;
    final gate = resumeGate;
    if (gate != null) await gate.future;
    return {'id': sessionId, 'status': 'active', 'active_seconds': 30};
  }
}

class _MultiPlanWardHomeApi extends _WardHomeApi {
  @override
  Future<Map<String, dynamic>> plan(String wardId, DateTime day) async => {
        'status': 'confirmed',
        'items': [
          {
            'id': 'plan-1',
            'assignment_id': 'planned-1',
            'title': '数学练习册 P23–25',
            'planned_minutes': 40,
            'start_at': '2026-09-20T19:00:00',
            'details': '学校作业',
            'status': 'scheduled',
            'session': {
              'id': 'session-math',
              'status': 'active',
              'active_seconds': 60,
            },
          },
          {
            'id': 'plan-2',
            'assignment_id': 'planned-2',
            'title': '休息',
            'planned_minutes': 10,
            'status': 'pending',
            'session': null,
          },
          {
            'id': 'plan-3',
            'assignment_id': 'planned-3',
            'title': '英语朗读三遍',
            'planned_minutes': 20,
            'details': '学校作业',
            'status': 'pending',
            'session': null,
          },
          {
            'id': 'plan-4',
            'assignment_id': 'planned-4',
            'title': '网课',
            'planned_minutes': 30,
            'details': '固定时间 · 不可移动',
            'status': 'pending',
            'session': null,
          },
        ],
      };
}

class _FakeVoice implements VoiceTranscription {
  late TranscriptHandler onPartial;
  late TranscriptHandler onFinal;
  late VoiceErrorHandler onError;
  var cancelled = false;
  var committed = false;
  String? failOnStartWith;
  var commitProducesFinal = true;
  String finalText = '今天整理错题';

  @override
  Future<void> start(
      {required TranscriptHandler onPartial,
      required TranscriptHandler onFinal,
      required VoiceErrorHandler onError}) async {
    this.onPartial = onPartial;
    this.onFinal = onFinal;
    this.onError = onError;
    final error = failOnStartWith;
    if (error != null) onError(error);
  }

  @override
  Future<void> cancel() async => cancelled = true;

  @override
  Future<void> commit() async {
    committed = true;
    if (commitProducesFinal) onFinal(finalText);
  }

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

  testWidgets('an in-progress card offers pause and finish from the session',
      (tester) async {
    final api = _ActiveTaskApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    expect(find.text('进行中'), findsOneWidget);
    await tester.tap(find.text('观察蚂蚁路线'));
    await tester.pumpAndSettle();
    expect(find.text('这项任务正在进行'), findsOneWidget);

    expect(find.byType(AlertDialog), findsOneWidget);
    await tester.tap(find.text('暂停'));
    await tester.pumpAndSettle();
    expect(find.text('确认暂停'), findsNothing);
    expect(find.text('暂停'), findsOneWidget);
    expect(find.text('进行中'), findsNothing);
    expect(api.pausedSessionId, 'session-live');
  });

  testWidgets('pause updates the card before the server answers',
      (tester) async {
    final api = _ActiveTaskApi()..pauseGate = Completer<void>();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('观察蚂蚁路线'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('暂停'));
    await tester.pumpAndSettle();

    expect(find.text('暂停'), findsOneWidget);
    expect(find.text('进行中'), findsNothing);
    api.pauseGate!.complete();
    await tester.pumpAndSettle();
    expect(find.text('暂停'), findsOneWidget);
  });

  testWidgets('resume updates the card before the server answers',
      (tester) async {
    final api = _PausedTaskApi()..resumeGate = Completer<void>();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    expect(find.text('暂停'), findsOneWidget);
    await tester.tap(find.text('观察蚂蚁路线'));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsOneWidget);
    await tester.tap(find.text('确认继续'));
    await tester.pumpAndSettle();

    expect(find.text('进行中'), findsOneWidget);
    expect(find.text('暂停'), findsNothing);
    api.resumeGate!.complete();
    await tester.pumpAndSettle();
    expect(find.text('进行中'), findsOneWidget);
  });

  testWidgets(
      'an in-progress card allows completing the task with rich dialog feedback',
      (tester) async {
    final api = _ActiveTaskApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('观察蚂蚁路线'));
    await tester.pumpAndSettle();
    expect(find.text('这项任务正在进行'), findsOneWidget);
    expect(find.text('已累计 2 分钟'), findsOneWidget);

    await tester.tap(find.text('完成任务'));
    await tester.pumpAndSettle();
    expect(find.text('完成这项任务？'), findsOneWidget);
    expect(find.text('本次累计专注时长：2 分钟'), findsOneWidget);

    await tester.tap(find.text('确认完成'));
    await tester.pumpAndSettle();
    expect(api.finishedSessionId, 'session-live');
    expect(find.textContaining('已完成「观察蚂蚁路线」'), findsOneWidget);
  });

  testWidgets('a paused card allows finishing directly from dialog',
      (tester) async {
    final api = _PausedTaskApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    expect(find.text('暂停'), findsOneWidget);
    await tester.tap(find.text('观察蚂蚁路线'));
    await tester.pumpAndSettle();
    expect(find.text('继续学习？'), findsOneWidget);
    expect(find.text('已累计学习 30 秒（进度已保留）'), findsOneWidget);

    await tester.tap(find.text('完成任务'));
    await tester.pumpAndSettle();
    expect(find.text('完成这项任务？'), findsOneWidget);

    await tester.tap(find.text('确认完成'));
    await tester.pumpAndSettle();
    expect(api.finishedSessionId, 'session-live');
    expect(find.textContaining('已完成「观察蚂蚁路线」'), findsOneWidget);
  });

  testWidgets('today plan card confirms before it starts', (tester) async {
    final api = _WardHomeApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('数学练习册').first);
    await tester.pumpAndSettle();
    expect(find.text('开始学习？'), findsOneWidget);
    expect(api.startedPlanItem, isNull);

    await tester.tap(find.text('确认开始'));
    await tester.pumpAndSettle();
    expect(api.startedPlanItem, 'plan-1');
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
    expect(find.text('19:00'), findsWidgets);
    expect(find.text('约 30 分钟'), findsWidgets);

    await tester.tap(find.text('数学练习册').last);
    await tester.pumpAndSettle();
    expect(find.text('开始学习？'), findsOneWidget);
  });

  testWidgets(
      'V3 home displays start times, planned durations, and timeline styles aligned with mockup',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(_MultiPlanWardHomeApi())],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    // 检查首页横滑计划轨中的开始时间与预计时长
    expect(find.text('19:00'), findsOneWidget);
    expect(find.text('数学练习册 P23–25'), findsOneWidget);
    expect(find.text('约 40 分钟'), findsOneWidget);
    expect(find.text('进行中'), findsOneWidget);

    expect(find.text('19:40'), findsOneWidget);
    expect(find.text('休息'), findsOneWidget);
    expect(find.text('约 10 分钟'), findsOneWidget);

    expect(find.text('19:50'), findsOneWidget);
    expect(find.text('英语朗读三遍'), findsOneWidget);
    expect(find.text('约 20 分钟'), findsOneWidget);

    expect(find.text('20:10'), findsOneWidget);
    expect(find.text('网课'), findsOneWidget);
    expect(find.text('固定 · 不可移动'), findsOneWidget);

    // 点击「全部」打开完整时间轴
    await tester.tap(find.text('全部'));
    await tester.pumpAndSettle();

    expect(find.text('今日计划'), findsOneWidget);
    expect(find.text('已确认 · 共 4 项 · 你说了算'), findsOneWidget);

    // 时间轴中的时间列与时长详情
    expect(find.text('19:00'), findsWidgets);
    expect(find.text('学校作业 · 约 40 分钟'), findsOneWidget);
    expect(find.text('19:40'), findsWidgets);
    expect(find.text('约 10 分钟'), findsWidgets);
    expect(find.text('19:50'), findsWidgets);
    expect(find.text('学校作业 · 约 20 分钟'), findsOneWidget);
    expect(find.text('20:10'), findsWidgets);
    expect(find.text('固定时间 · 不可移动'), findsOneWidget);

    await tester.tap(find.text('休息').last);
    await tester.pumpAndSettle();
    expect(find.text('开始学习？'), findsOneWidget);
  });

  testWidgets('V3 home deletes a task-pool item when swiped', (tester) async {
    final api = _WardHomeApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    await tester.drag(find.text('观察蚂蚁路线'), const Offset(-500, 0));
    await tester.pumpAndSettle();
    expect(find.text('观察蚂蚁路线'), findsNothing);
    expect(find.text('今天没有待定项了。想加任务，走下方统一入口。'), findsOneWidget);
    expect(api.deleted, ['pool-1']);
  });

  testWidgets('read-aloud asks for pronunciation and plays the lesson',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi();
    final playback = _FakePlayback();
    final voice = _FakeVoice()..finalText = 'apple';
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
          home: WardDayPage(
              wardId: 'ward-1',
              speechPlayback: () => playback,
              voiceFactory: (
                      {required baseUrl,
                      required tokens,
                      required telemetry}) =>
                  voice)),
    ));
    await tester.pumpAndSettle();

    final gesture = await tester
        .startGesture(tester.getCenter(find.text('说出你的任何想法、问题、安排')));
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.up();
    await tester.pumpAndSettle();

    expect(api.turns.single.content, 'apple');
    expect(find.text('apple'), findsWidgets);
    expect(playback.played, isEmpty);

    await tester.ensureVisible(find.text('0.75x'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('0.75x'));
    await tester.pump();
    await tester.ensureVisible(find.text('播放'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('播放'));
    await tester.pumpAndSettle();

    expect(api.speechRates, [0.75]);
    expect(playback.played, isNotEmpty);
    expect(find.text('正在播放'), findsOneWidget);
  });

  testWidgets('multi-word pronunciation renders multiple cards',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi();
    final playback = _FakePlayback();
    final voice = _FakeVoice()..finalText = 'start also';
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
          home: WardDayPage(
              wardId: 'ward-1',
              speechPlayback: () => playback,
              voiceFactory: (
                      {required baseUrl,
                      required tokens,
                      required telemetry}) =>
                  voice)),
    ));
    await tester.pumpAndSettle();

    final gesture = await tester
        .startGesture(tester.getCenter(find.text('说出你的任何想法、问题、安排')));
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.up();
    await tester.pumpAndSettle();

    expect(find.text('start（开始）', skipOffstage: false), findsOneWidget);
    expect(find.text('also（也）', skipOffstage: false), findsOneWidget);
  });

  testWidgets(
      'a text_visual answer draws the diagram in the bubble and keeps it on subsequent turns',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi();
    final voice = _FakeVoice()..finalText = '水循环是怎么回事';
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
          home: WardDayPage(
              wardId: 'ward-1',
              voiceFactory: (
                      {required baseUrl,
                      required tokens,
                      required telemetry}) =>
                  voice)),
    ));
    await tester.pumpAndSettle();

    var gesture = await tester
        .startGesture(tester.getCenter(find.text('说出你的任何想法、问题、安排')));
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.up();
    await tester.pumpAndSettle();
    final block =
        find.byKey(const ValueKey('visual-block'), skipOffstage: false);
    expect(block, findsOneWidget);
    expect(find.text('蒸发', skipOffstage: false), findsOneWidget);

    voice.finalText = '谢谢';
    gesture = await tester
        .startGesture(tester.getCenter(find.text('说出你的任何想法、问题、安排')));
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.up();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('visual-block'), skipOffstage: false),
        findsOneWidget);
    expect(find.text('蒸发', skipOffstage: false), findsOneWidget);
  });

  testWidgets('a picked chat image stays as a thumbnail until send',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
          home: WardDayPage(
              wardId: 'ward-1',
              pickChatImage: () async => PickedChatImage(
                  bytes: Uint8List.fromList(_tinyPng), extension: 'png'))),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('拍照'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('staged-image-strip')), findsOneWidget);
    expect(api.turns, isEmpty);

    await tester.tap(find.byTooltip('发送'));
    await tester.pumpAndSettle();

    expect(api.turns, hasLength(1));
    expect(api.turns.single.content, '请看这张图片。');
    expect(api.turns.single.attachmentKeys, ['ward/ward-1/companion/test.png']);
    expect(find.byKey(const Key('staged-image-strip')), findsNothing);
    expect(find.byKey(const ValueKey('sent-chat-image-0')), findsOneWidget);
    expect(find.text('请看这张图片。'), findsNothing);
  });

  testWidgets('ward messages sit on the right within two thirds and omit 我',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi();
    const spoken = '今晚先读十分钟课外书，然后再做两道数学题，看看时间够不够。';
    final voice = _FakeVoice()..finalText = spoken;
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
          home: WardDayPage(
              wardId: 'ward-1',
              voiceFactory: (
                      {required baseUrl,
                      required tokens,
                      required telemetry}) =>
                  voice)),
    ));
    await tester.pumpAndSettle();

    final gesture = await tester
        .startGesture(tester.getCenter(find.text('说出你的任何想法、问题、安排')));
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.up();
    await tester.pumpAndSettle();

    expect(find.text('我'), findsNothing);
    expect(find.text('读学 AI'), findsWidgets);

    final list = tester.getRect(find.byKey(const Key('companion-chat-list')));
    final contentLeft = list.left + 16;
    final contentRight = list.right - 16;
    final contentWidth = contentRight - contentLeft;
    final ward = tester.getRect(find.byKey(const ValueKey(
        'chat-bubble-ward-今晚先读十分钟课外书，然后再做两道数学题，看看时间够不够。')));
    final ai = tester.getRect(find.byKey(const ValueKey(
        'chat-bubble-ai-我不会替你排今天。你说想怎么安排，我帮你记下来，并检查有没有冲突。')));

    expect(ward.right, closeTo(contentRight, 1));
    expect(ward.width, lessThanOrEqualTo(contentWidth * 2 / 3 + 1));
    expect(ward.width, greaterThan(contentWidth * 0.5));
    expect(ai.left, closeTo(contentLeft, 1));
    expect(ai.width, greaterThan(contentWidth * 2 / 3));
  });

  testWidgets('spoken text is sent together with the staged image',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi();
    final voice = _FakeVoice()..finalText = '把这页作业排到今晚';
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
          home: WardDayPage(
              wardId: 'ward-1',
              voiceFactory: (
                      {required baseUrl,
                      required tokens,
                      required telemetry}) =>
                  voice,
              pickChatImage: () async => PickedChatImage(
                  bytes: Uint8List.fromList(_tinyPng), extension: 'png'))),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('拍照'));
    await tester.pumpAndSettle();
    final gesture = await tester
        .startGesture(tester.getCenter(find.text('说出你的任何想法、问题、安排')));
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.up();
    await tester.pumpAndSettle();

    expect(api.turns.single.content, '把这页作业排到今晚');
    expect(api.turns.single.attachmentKeys, ['ward/ward-1/companion/test.png']);
  });

  testWidgets('removing the staged image does not send it', (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp(
          home: WardDayPage(
              wardId: 'ward-1',
              pickChatImage: () async => PickedChatImage(
                  bytes: Uint8List.fromList(_tinyPng), extension: 'png'))),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('拍照'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('移除图片'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('staged-image-strip')), findsNothing);
    expect(api.turns, isEmpty);
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
    await tester.tap(find.text('拍照'));

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

  testWidgets(
      'a startup recognition error does not leave the listening overlay',
      (tester) async {
    final voice = _FakeVoice()
      ..failOnStartWith = 'voice transcription is temporarily unavailable'
      ..commitProducesFinal = false;
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
                onVoiceFinal: (_) async {},
                onPickImage: () async {}))));

    final gesture =
        await tester.startGesture(tester.getCenter(find.text('按住说话')));
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pump();
    await gesture.up();
    await tester.pump();

    expect(find.text('正在听…上滑取消'), findsNothing);
    expect(find.text('松开发送'), findsNothing);
    expect(find.text('voice transcription is temporarily unavailable'),
        findsOneWidget);
  });

  testWidgets(
      'login page binds ward directly in place when 6-digit code is entered',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi();
    final router = GoRouter(
      initialLocation: '/login',
      routes: [
        GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
        GoRoute(
          path: '/ward-day/:id',
          builder: (_, state) =>
              WardDayPage(wardId: state.pathParameters['id']!),
        ),
      ],
    );
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: MaterialApp.router(routerConfig: router),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('我是孩子'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('ward-bind-code-input')), findsOneWidget);
    await tester.enterText(
        find.byKey(const Key('ward-bind-code-input')), '123456');
    await tester.pumpAndSettle();

    expect(api.boundCode, '123456');
    expect(find.text('晚上好，小读'), findsOneWidget);
  });

  testWidgets(
      'guardian empty state focuses on creating a ward and immediately pops up the 6-digit binding code',
      (tester) async {
    final api = _WardHomeApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardListPage()),
    ));
    await tester.pumpAndSettle();

    expect(find.text('传递作业、通知或留言'), findsNothing);
    expect(find.text('还没有孩子档案'), findsOneWidget);
    expect(find.text('新增孩子档案'), findsOneWidget);

    await tester.tap(find.text('新增孩子档案'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '小宇');
    await tester.tap(find.text('创建并进入'));
    await tester.pumpAndSettle();

    expect(api.invitedWardId, 'ward-new');
    expect(find.text('小宇 · 学生 App 绑定码'), findsOneWidget);
    expect(find.text('654321'), findsOneWidget);

    await tester.tap(find.text('完成'));
    await tester.pumpAndSettle();

    expect(find.text('传递作业、通知或留言'), findsOneWidget);
    expect(find.text('获取绑定码'), findsOneWidget);
  });

  testWidgets(
      'ward home restores latest companion thread and loads older messages across pages and previous threads with virtualized ListView',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi()
      ..currentTranscriptOverride = {
        'thread_id': 'thread-new',
        'thread_version': 4,
        'next_before_thread_version': 3,
        'previous_thread_id': null,
        'messages': [
          {
            'id': 'm-3',
            'thread_id': 'thread-new',
            'thread_version': 3,
            'author_type': 'ward',
            'content': '最新一轮提问',
            'attachment_refs': const <String>[],
          },
          {
            'id': 'm-4',
            'thread_id': 'thread-new',
            'thread_version': 4,
            'author_type': 'companion',
            'content': '最新一轮回答',
            'attachment_refs': const <String>[],
          },
        ],
      };
    api.threadTranscriptOverrides['thread-new:3'] = {
      'thread_id': 'thread-new',
      'thread_version': 4,
      'next_before_thread_version': null,
      'previous_thread_id': 'thread-old',
      'messages': [
        {
          'id': 'm-1',
          'thread_id': 'thread-new',
          'thread_version': 1,
          'author_type': 'ward',
          'content': '当前线程较早提问',
          'attachment_refs': const <String>[],
        },
        {
          'id': 'm-2',
          'thread_id': 'thread-new',
          'thread_version': 2,
          'author_type': 'companion',
          'content': '当前线程较早回答',
          'attachment_refs': const <String>[],
        },
      ],
    };
    api.threadTranscriptOverrides['thread-old:latest'] = {
      'thread_id': 'thread-old',
      'thread_version': 2,
      'next_before_thread_version': null,
      'previous_thread_id': null,
      'messages': [
        {
          'id': 'm-old-1',
          'thread_id': 'thread-old',
          'thread_version': 1,
          'author_type': 'ward',
          'content': '重绑前的历史提问',
          'attachment_refs': const <String>[],
        },
        {
          'id': 'm-old-2',
          'thread_id': 'thread-old',
          'thread_version': 2,
          'author_type': 'companion',
          'content': '重绑前的历史回答',
          'attachment_refs': const <String>[],
        },
      ],
    };

    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('说出你的任何想法、问题、安排'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('companion-chat-list')), findsOneWidget);
    expect(find.text('最新一轮提问'), findsOneWidget);
    expect(find.text('最新一轮回答'), findsOneWidget);
    expect(find.byKey(const Key('load-older-messages-button')), findsOneWidget);

    // Load older page within thread-new
    await tester.tap(find.byKey(const Key('load-older-messages-button')));
    await tester.pumpAndSettle();

    expect(find.text('当前线程较早提问'), findsOneWidget);
    expect(find.text('当前线程较早回答'), findsOneWidget);

    // Drag down to scroll back to the top; scrolling near the top triggers loading thread-old
    await tester.drag(
        find.byKey(const Key('companion-chat-list')), const Offset(0, 300));
    await tester.pumpAndSettle();

    expect(find.text('重绑前的历史提问'), findsOneWidget);
    expect(find.text('重绑前的历史回答'), findsOneWidget);
    expect(find.byKey(const Key('load-older-messages-button')), findsNothing);
  });
}
