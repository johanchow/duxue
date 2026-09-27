import 'dart:async';

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
  String? startedPlanItem;
  String? pausedSessionId;
  String? finishedSessionId;
  final deleted = <String>[];

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
    Map<String, dynamic>? structuredCommand,
    List<String> attachmentKeys = const [],
  }) async {
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
  Future<Map<String, dynamic>> companionMessages(String threadId) async =>
      const {'thread_version': 1, 'messages': []};
}

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
    if (commitProducesFinal) onFinal('今天整理错题');
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

  testWidgets('an in-progress card allows completing the task with rich dialog feedback',
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

  testWidgets('a startup recognition error does not leave the listening overlay',
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
}
