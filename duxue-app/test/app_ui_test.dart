import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/models.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/core/voice_transcription_service.dart';
import 'package:duxue_app/core/speech_playback.dart';
import 'package:duxue_app/core/telemetry.dart';
import 'package:duxue_app/features/day_story_pages.dart';
import 'package:duxue_app/features/login_page.dart';
import 'package:duxue_app/features/ward_pages.dart';
import 'package:duxue_app/main.dart' show routerProvider;
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
  bool showPlanSuggestions = false;
  bool showClarifyAdvice = false;
  bool suggestMissingDuration = false;
  bool showIntentChoice = false;
  bool showSprintProposal = false;
  Map<String, dynamic>? lastStructuredCommand;
  final deleted = <String>[];
  final turns = <({String content, List<String> attachmentKeys})>[];

  @override
  Future<DailyReport> report(String wardId, DateTime date) async => DailyReport(
      status: 'empty',
      date: date,
      totalSeconds: 0,
      breakdown: const {},
      timeline: const [],
      profileChanged: false);
  @override
  Future<List<Map<String, dynamic>>> tutoringEvidence(
          String wardId, DateTime date) async =>
      [];

  @override
  Future<Map<String, dynamic>> currentSprint() async =>
      {'sprint': null, 'ready': null};

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
    submittedThreads.add(threadId);
    if (delayedTurn != null) return delayedTurn!.future;
    lastStructuredCommand = structuredCommand;
    lastRouteHint = routeHint;
    lastTutoringIntent = tutoringIntent;
    turns.add((
      content: content,
      attachmentKeys: List<String>.from(attachmentKeys),
    ));
    if (showSprintProposal) {
      return {
        'thread_id': threadId ?? 'thread-1',
        'thread_version': (expectedThreadVersion ?? 0) + 2,
        'interaction': {
          'kind': 'sprint_control',
          'parts': [
            {'text': '试一轮十分钟？'}
          ],
          'actions': [
            {
              'id': 'issued-sprint-start',
              'command': 'sprint_command',
              'enabled': true,
              'payload': {'action': 'start'}
            }
          ]
        }
      };
    }
    if (showIntentChoice) {
      if (structuredCommand == null) {
        return {
          'thread_id': threadId ?? 'thread-1',
          'thread_version': (expectedThreadVersion ?? 0) + 2,
          'interaction': {
            'protocol': 'companion-interaction.v1',
            'kind': 'intent_choice',
            'content': '请选你想做的事。',
            'parts': [
              {'type': 'text', 'text': '请选你想做的事。'},
            ],
            'actions': [
              for (final choice in [
                ('planning', '管理任务'),
                ('reflection', '总结思考'),
                ('tutoring', '提问探讨'),
              ])
                {
                  'id': 'intent:thread-1:source',
                  'command': 'choose_intent',
                  'label': choice.$2,
                  'enabled': true,
                  'payload': {'intent': choice.$1},
                },
            ],
          },
        };
      }
      return {
        'thread_id': threadId ?? 'thread-1',
        'thread_version': (expectedThreadVersion ?? 0) + 2,
        'interaction': {
          'kind': 'text',
          'parts': [
            {'type': 'text', 'text': '已按选择继续。'},
          ],
        },
      };
    }
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
      if (showPlanSuggestions || suggestMissingDuration) {
        return {
          'thread_id': threadId ?? 'thread-1',
          'thread_version': (expectedThreadVersion ?? 0) + 2,
          'interaction': {
            'kind': 'plan_confirm_list',
            'parts': [
              {'type': 'text', 'text': '已采用建议，请检查草稿。'}
            ],
            'object_ref': {'context': 'planning', 'object_id': 'draft-1'},
            'actions': [
              {
                'id': 'plan:run:1:draft-1:3',
                'command': 'confirm_plan',
                'enabled': true
              },
            ],
          },
        };
      }
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
        'kind': suggestMissingDuration || showClarifyAdvice
            ? 'clarify'
            : 'plan_confirm_list',
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
            'command': suggestMissingDuration || showClarifyAdvice
                ? 'clarify_reply'
                : 'confirm_plan',
            'enabled': true
          },
          if (showPlanSuggestions || showClarifyAdvice)
            {
              'id': 'plan:run:1:draft-1:2',
              'command': 'accept_plan_suggestion',
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
          {
            'assignment_id': 'task-1',
            'title': '整理错题',
            'planned_minutes': 20,
            if (showPlanSuggestions || showClarifyAdvice) ...{
              'duration_suggestion': {
                'suggested_minutes': 35,
                'sample_count': 3,
                'actual_median_minutes': 35,
                'fingerprint': 'duration-sample',
              },
              'time_suggestion': {
                'reason': '建议在22:00前结束',
                'suggested_start_at':
                    showClarifyAdvice ? null : '2026-10-22T21:25:00+08:00',
                'suggested_end_at':
                    showClarifyAdvice ? null : '2026-10-22T22:00:00+08:00',
                'fingerprint': 'time-sample',
              },
            },
          },
        ],
        if (suggestMissingDuration)
          'clarification_batch': {
            'slots': [
              {
                'slot_id': 'slot-1',
                'field': 'planned_minutes',
                'title': '英语阅读',
                'duration_suggestion': {
                  'suggested_minutes': 25,
                  'sample_count': 3,
                  'actual_median_minutes': 25,
                  'fingerprint': 'clarification-sample',
                },
              },
            ],
          },
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

  final clearCommands = <String>[];
  bool clearFails = false;
  Completer<Map<String, dynamic>>? delayedTurn;
  Completer<Map<String, dynamic>>? delayedHistory;
  final submittedThreads = <String?>[];

  @override
  Future<Map<String, dynamic>> clearCompanionHistory(String commandId) async {
    clearCommands.add(commandId);
    if (clearFails) throw StateError('offline');
    currentTranscriptOverride = {
      'thread_id': null,
      'thread_version': 0,
      'messages': <dynamic>[],
      'next_before_thread_version': null,
      'previous_thread_id': null,
    };
    threadTranscriptOverrides.clear();
    return {'history_generation': 1};
  }

  Map<String, dynamic>? currentTranscriptOverride;
  final Map<String, Map<String, dynamic>> threadTranscriptOverrides = {};
  final List<({String threadId, int? beforeThreadVersion, int limit})>
      transcriptCalls = [];
  final imageCalls = <String>[];

  @override
  Future<Uint8List> companionMessageImage(String messageId, int index) async {
    imageCalls.add('$messageId:$index');
    return Uint8List.fromList(_tinyPng);
  }

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
    if (delayedHistory != null) return delayedHistory!.future;
    if (showIntentChoice) {
      final choiceActions = [
        for (final choice in [
          ('planning', '管理任务'),
          ('reflection', '总结思考'),
          ('tutoring', '提问探讨'),
        ])
          {
            'id': 'intent:thread-1:source',
            'command': 'choose_intent',
            'label': choice.$2,
            'enabled': true,
            'payload': {'intent': choice.$1},
          },
      ];
      return {
        'thread_id': threadId,
        'thread_version': turns.length * 2,
        'messages': [
          if (turns.isNotEmpty) ...[
            {
              'author_type': 'ward',
              'content': turns.first.content,
              'thread_id': threadId,
              'thread_version': 1
            },
            {
              'author_type': 'companion',
              'content': '请选你想做的事。',
              'thread_id': threadId,
              'thread_version': 2,
              'interaction_ref': {
                'kind': 'intent_choice',
                'actions': choiceActions
              }
            },
          ],
          if (turns.length > 1) ...[
            {
              'author_type': 'ward',
              'content': turns.last.content,
              'thread_id': threadId,
              'thread_version': 3
            },
            {
              'author_type': 'companion',
              'content': '已按选择继续。',
              'thread_id': threadId,
              'thread_version': 4
            },
          ],
        ],
      };
    }
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
          if (turn.content == 'apple' || turn.content == 'start also')
            {
              'author_type': 'companion',
              'content':
                  turn.content == 'apple' ? '先听这个词。' : 'start 是开始，also 是也。',
              'attachment_refs': const <String>[],
              'interaction_ref': {
                'kind': 'pronunciation_lesson',
                'lessons': turn.content == 'apple'
                    ? [
                        {
                          'source_text': 'apple',
                          'locale': 'en-US',
                          'introduction': '先听这个词。',
                          'speech_ref': 'lesson-1',
                          'supported_rates': [0.5, 0.75, 1.0],
                        },
                      ]
                    : [
                        {
                          'source_text': 'start',
                          'locale': 'en-US',
                          'introduction': 'start（开始）',
                          'speech_ref': 'lesson-multi',
                          'supported_rates': [0.5, 0.75, 1.0],
                        },
                        {
                          'source_text': 'also',
                          'locale': 'en-US',
                          'introduction': 'also（也）',
                          'speech_ref': 'lesson-multi:1',
                          'supported_rates': [0.5, 0.75, 1.0],
                        },
                      ],
              },
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

class _EmailAuthApi extends _WardHomeApi {
  String? sentTo;
  (String, String, String)? registration;

  @override
  Future<void> sendEmailCode(String email) async => sentTo = email;

  @override
  Future<void> register(String name, String email, String code) async {
    registration = (name, email, code);
  }
}

class _MissingGuardianApi extends _EmailAuthApi {
  @override
  Future<void> login(String email, String code) async {
    final request = RequestOptions(path: '/auth/login');
    throw DioException(
      requestOptions: request,
      response: Response(
        requestOptions: request,
        statusCode: 404,
        data: {'detail': 'account not found'},
      ),
      type: DioExceptionType.badResponse,
    );
  }
}

class _InvalidEmailCodeApi extends _EmailAuthApi {
  @override
  Future<void> register(String name, String email, String code) async {
    final request = RequestOptions(path: '/auth/register');
    throw DioException(
      requestOptions: request,
      response: Response(requestOptions: request, statusCode: 400),
      type: DioExceptionType.badResponse,
    );
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

class _SprintApi extends _WardHomeApi {
  Map<String, dynamic>? round;
  Map<String, dynamic> preview = {
    'status': 'ready',
    'topic': '数学',
    'target_minutes': 20,
    'message': '数学 · 20分钟'
  };
  final spokenPreviews = <Map<String, dynamic>>[];
  Completer<Map<String, dynamic>>? delayedPreview;
  @override
  Future<Map<String, dynamic>> previewSprint(String content,
      {Map<String, dynamic>? previous}) async {
    spokenPreviews.add({'content': content, 'previous': previous});
    if (failPreview) throw StateError('offline');
    return delayedPreview == null ? preview : delayedPreview!.future;
  }

  bool failPause = false;
  bool failPreview = false;
  bool failCreate = false;
  final createCommands = <String>[];
  int creates = 0;
  final actions = <String>[];
  @override
  Future<Map<String, dynamic>> currentSprint() async =>
      {'sprint': round, 'ready': null};
  @override
  Future<Map<String, dynamic>> createSprint(Map<String, dynamic> data) async {
    createCommands.add(data['command_id'] as String? ?? 'test');
    if (failCreate) throw StateError('offline');
    creates++;
    round = {
      'id': 'sprint-1',
      'topic': data['topic'],
      'status': 'active',
      'version': 1,
      'remaining_seconds': 1200,
      'target_seconds': 1200
    };
    return {'sprint': round};
  }

  @override
  Future<Map<String, dynamic>> sprintCommand(
      String id, Map<String, dynamic> data) async {
    final action = data['action'] as String;
    actions.add(action);
    if (action == 'pause' && failPause) throw StateError('offline');
    if (action == 'end') {
      round = null;
    } else {
      round = {
        ...round!,
        'status': action == 'pause' ? 'paused' : 'active',
        'version': (round!['version'] as int) + 1
      };
    }
    return {'sprint': round};
  }
}

class _NoticeSprintApi extends _SprintApi {
  bool noticeAvailable = false;
  final claim = Completer<Map<String, dynamic>>();
  @override
  Future<Map<String, dynamic>> currentSprint() async => {
        'sprint': null,
        'ready': null,
        if (noticeAvailable)
          'notice': {'id': 'elapsed-round', 'version': 2, 'status': 'elapsed'}
      };
  @override
  Future<Map<String, dynamic>> sprintCommand(
      String id, Map<String, dynamic> data) async {
    if (data['action'] == 'claim_notice') {
      actions.add('claim_notice');
      noticeAvailable = false;
      return claim.future;
    }
    return super.sprintCommand(id, data);
  }
}

class _DelayedSprintApi extends _SprintApi {
  final firstRead = Completer<Map<String, dynamic>>();
  int reads = 0;
  @override
  Future<Map<String, dynamic>> currentSprint() async {
    reads++;
    if (reads == 1) return firstRead.future;
    return super.currentSprint();
  }
}

Future<void> _wardMenu(WidgetTester tester, String label) async {
  await tester.tap(find.byTooltip('更多'));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
  await tester.tap(find.text(label).last);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 300));
}

Future<void> _voiceSprintHome(WidgetTester tester, _SprintApi api) async {
  await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
  await tester.pumpAndSettle();
  await tester.tap(find.byTooltip('专注挑战'));
  await tester.pumpAndSettle();
}

Future<void> _speakSprint(WidgetTester tester, String text) async {
  await tester
      .widget<VoiceComposer>(find.byType(VoiceComposer))
      .onVoiceFinal(text);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('natural challenge confirmation stays beside the latest turn',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _SprintApi()..showSprintProposal = true;
    for (var i = 0; i < 20; i++) {
      api.turns.add((content: '前面的解题讨论第$i轮', attachmentKeys: <String>[]));
    }
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('帮我开启十分钟专注挑战');
    await tester.pumpAndSettle();
    expect(find.text('开始这次挑战').hitTestable(), findsOneWidget);
    expect(api.creates, 0);
  });

  testWidgets('claimed sprint notice waits for the ongoing tutoring reply',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final pending = Completer<Map<String, dynamic>>();
    final api = _NoticeSprintApi()..delayedTurn = pending;
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    api.noticeAvailable = true;
    await tester.pump(const Duration(seconds: 30));
    await tester.pump();
    expect(api.actions, ['claim_notice']);
    final turn = tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('这道题下一步怎么想？');
    await tester.pump();
    api.claim.complete({});
    await tester.pump();
    const notice = '这轮计时结束了，要继续还是休息？';
    expect(find.text(notice), findsNothing);
    pending.complete({
      'thread_id': 'notice-thread',
      'thread_version': 1,
      'interaction': {
        'kind': 'text',
        'parts': [
          {'text': '先看看题目的已知条件。'}
        ]
      }
    });
    await turn;
    await tester.pumpAndSettle();
    expect(find.text(notice), findsOneWidget);
    await tester.pump(const Duration(seconds: 30));
    await tester.pumpAndSettle();
    expect(api.actions, ['claim_notice']);
  });

  testWidgets('leaving home invalidates a pending spoken preview',
      (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _SprintApi()..delayedPreview = pending;
    await _voiceSprintHome(tester, api);
    final result = tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('数学二十分钟');
    await tester.pump();
    await tester.tap(find.text('成长'));
    await tester.pumpAndSettle();
    pending.complete(api.preview);
    await result;
    await tester.tap(find.text('首页'));
    await tester.pumpAndSettle();
    expect(find.text('开始本轮'), findsNothing);
    expect(find.text('先做手边的一小步'), findsOneWidget);
    expect(api.creates, 0);
  });

  testWidgets(
      'a round started on another device replaces an obsolete voice confirmation',
      (tester) async {
    final api = _SprintApi();
    await _voiceSprintHome(tester, api);
    await _speakSprint(tester, '数学二十分钟');
    await api.createSprint({'topic': '阅读'});
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(find.text('开始本轮'), findsNothing);
    expect(find.text('阅读 · 专注挑战'), findsOneWidget);
    expect(api.creates, 1);
  });

  testWidgets('voice confirmation and original composer fit a small phone',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await _voiceSprintHome(tester, _SprintApi());
    await _speakSprint(tester, '数学二十分钟');
    expect(find.text('开始本轮'), findsOneWidget);
    expect(find.byType(VoiceComposer), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('late ASR after cancel never becomes an ordinary chat message',
      (tester) async {
    final api = _SprintApi();
    await _voiceSprintHome(tester, api);
    final composer = tester.widget<VoiceComposer>(find.byType(VoiceComposer));
    await composer.onBeforeRecording!();
    await tester.tap(find.byTooltip('取消专注挑战'));
    await tester.pumpAndSettle();
    await composer.onVoiceFinal('数学二十分钟');
    await tester.pumpAndSettle();
    expect(api.spokenPreviews, isEmpty);
    expect(api.turns, isEmpty);
    expect(find.byKey(const Key('companion-chat-list')), findsNothing);
  });

  testWidgets(
      'sprint asks only for missing duration and supports spoken corrections',
      (tester) async {
    final api = _SprintApi()
      ..preview = {
        'status': 'needs_duration',
        'topic': '数学',
        'target_minutes': null,
        'message': '想试多久？'
      };
    await _voiceSprintHome(tester, api);
    await _speakSprint(tester, '写数学');
    expect(find.text('想试多久？'), findsOneWidget);
    expect(find.text('开始本轮'), findsNothing);
    api.preview = {
      'status': 'ready',
      'topic': '数学',
      'target_minutes': 15,
      'message': '数学 · 15分钟'
    };
    await _speakSprint(tester, '十五分钟');
    expect(api.spokenPreviews.last['previous'],
        {'topic': '数学', 'target_minutes': null});
    await tester.tap(find.text('重新说'));
    await tester.pumpAndSettle();
    expect(find.text('开始本轮'), findsNothing);
    api.preview = {
      'status': 'ready',
      'topic': '英语',
      'target_minutes': 10,
      'message': '英语 · 10分钟'
    };
    await _speakSprint(tester, '改成英语十分钟');
    expect(find.text('英语 · 10分钟'), findsOneWidget);
    expect(api.creates, 0);
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets(
      'duration-only speech stays generic and does not infer an existing assignment',
      (tester) async {
    final api = _SprintApi()
      ..preview = {
        'status': 'ready',
        'topic': '专注挑战',
        'target_minutes': 20,
        'message': '专注挑战 · 20分钟'
      };
    await _voiceSprintHome(tester, api);
    await _speakSprint(tester, '专心二十分钟');
    expect(find.text('专注挑战 · 20分钟'), findsOneWidget);
    expect(find.text('数学练习册'), findsNothing);
    expect(api.spokenPreviews.single['previous'], isNull);
  });

  testWidgets(
      'canceling an in-flight voice preview never revives its confirmation',
      (tester) async {
    final pending = Completer<Map<String, dynamic>>();
    final api = _SprintApi()..delayedPreview = pending;
    await _voiceSprintHome(tester, api);
    final recognition = tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('数学二十分钟');
    await tester.pump();
    await tester.tap(find.byTooltip('取消专注挑战'));
    await tester.pumpAndSettle();
    pending.complete(api.preview);
    await recognition;
    await tester.pumpAndSettle();
    expect(find.text('先做手边的一小步'), findsOneWidget);
    expect(find.text('开始本轮'), findsNothing);
    expect(api.creates, 0);
    expect(find.byKey(const Key('companion-chat-list')), findsNothing);
  });

  testWidgets('spoken cancellation exits setup without creating a sprint',
      (tester) async {
    final api = _SprintApi()
      ..preview = {
        'status': 'cancelled',
        'topic': null,
        'target_minutes': null,
        'message': '先直接做作业。'
      };
    await _voiceSprintHome(tester, api);
    await _speakSprint(tester, '先不用挑战了');
    expect(find.byTooltip('取消专注挑战'), findsNothing);
    expect(find.text('先做手边的一小步'), findsOneWidget);
    expect(api.creates, 0);
  });

  testWidgets('voice preview and confirmed start failures remain retryable',
      (tester) async {
    final api = _SprintApi()..failPreview = true;
    await _voiceSprintHome(tester, api);
    await _speakSprint(tester, '数学二十分钟');
    expect(find.text('重试整理'), findsOneWidget);
    expect(find.text('开始本轮'), findsNothing);
    api.failPreview = false;
    await tester.tap(find.text('重试整理'));
    await tester.pumpAndSettle();
    api.failCreate = true;
    await tester.tap(find.text('开始本轮'));
    await tester.pumpAndSettle();
    expect(api.creates, 0);
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
    api.failCreate = false;
    await tester.tap(find.text('开始本轮'));
    await tester.pumpAndSettle();
    expect(api.createCommands.length, 2);
    expect(api.createCommands.first, api.createCommands.last);
    expect(api.creates, 1);
  });

  testWidgets('canceling camera capture leaves the quiet homepage intact',
      (tester) async {
    var captures = 0;
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(_SprintApi())],
        child: MaterialApp(
            home: WardDayPage(
                wardId: 'ward-1',
                pickChatImage: () async {
                  captures++;
                  return null;
                }))));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('拍照'));
    await tester.pumpAndSettle();
    expect(captures, 1);
    expect(find.byKey(const Key('companion-chat-list')), findsNothing);
  });

  testWidgets(
      'closing a conversation preserves a late reply without reopening it',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final pending = Completer<Map<String, dynamic>>();
    final api = _SprintApi()..delayedTurn = pending;
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    final turn = tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('我想问一道题');
    await tester.pump();
    await tester.tap(find.byTooltip('收起对话'));
    await tester.pumpAndSettle();
    api.threadTranscriptOverrides['kept-thread:latest'] = {
      'thread_id': 'kept-thread',
      'thread_version': 2,
      'messages': [
        {
          'id': 'kept-reply',
          'author_type': 'companion',
          'content': '先看看已知条件。',
          'thread_version': 2
        }
      ]
    };
    pending.complete({
      'thread_id': 'kept-thread',
      'thread_version': 2,
      'interaction': {
        'kind': 'text',
        'parts': [
          {'text': '先看看已知条件。'}
        ]
      }
    });
    await turn;
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('companion-chat-list')), findsNothing);
    expect(find.text('继续上次对话'), findsNothing);
    expect(await const TokenStorage().companionThreadId, 'kept-thread');
    await tester.tap(find.byTooltip('更多'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('历史对话'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('companion-chat-list')), findsOneWidget);
  });

  testWidgets(
      'chat sprint preview preserves the conversation and can cancel or start',
      (tester) async {
    final api = _SprintApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('更多'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('历史对话'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('companion-chat-list')), findsOneWidget);
    await tester.tap(find.byTooltip('对话内专注挑战'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('companion-chat-list')), findsOneWidget);
    await _speakSprint(tester, '数学二十分钟');
    expect(api.creates, 0);
    await tester.tap(find.byTooltip('取消专注挑战'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('companion-chat-list')), findsOneWidget);
    await tester.tap(find.byTooltip('对话内专注挑战'));
    await tester.pumpAndSettle();
    await _speakSprint(tester, '数学二十分钟');
    await tester.tap(find.text('开始本轮'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('active-sprint-card')), findsOneWidget);
    expect(find.byKey(const Key('companion-chat-list')), findsOneWidget);
    expect(api.creates, 1);
  });

  testWidgets('ward lands quietly and only opens conversations on request',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(_SprintApi())],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    expect(find.text('先做手边的一小步'), findsOneWidget);
    expect(find.byKey(const Key('companion-chat-list')), findsNothing);
    expect(find.byIcon(Icons.local_fire_department_outlined), findsOneWidget);
    expect(find.byType(VoiceComposer), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    await tester.tap(find.byTooltip('更多'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('历史对话'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('companion-chat-list')), findsOneWidget);
    await tester.tap(find.byTooltip('收起对话'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('companion-chat-list')), findsNothing);
  });

  testWidgets(
      'spoken sprint is a read-only preview and only starts after confirmation',
      (tester) async {
    final api = _SprintApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('专注挑战'));
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsNothing);
    expect(find.byType(VoiceComposer), findsOneWidget);
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('数学，先试二十分钟');
    await tester.pumpAndSettle();
    expect(api.creates, 0);
    expect(find.text('数学 · 20分钟'), findsOneWidget);
    await tester.tap(find.text('开始本轮'));
    await tester.pumpAndSettle();
    expect(api.creates, 1);
    expect(find.byKey(const Key('active-sprint-card')), findsOneWidget);
    expect(find.byKey(const Key('companion-chat-list')), findsNothing);
    expect(api.turns, isEmpty);
  });

  testWidgets('guardian task transfer is a secondary child operation',
      (tester) async {
    await tester.pumpWidget(ProviderScope(overrides: [
      apiProvider.overrideWithValue(_WardHomeApi()),
      wardsProvider.overrideWith((ref) async => const [
            Ward(id: 'ward-1', displayName: '小宇', gradeStage: 'primary'),
          ]),
    ], child: const MaterialApp(home: WardListPage())));
    await tester.pumpAndSettle();
    expect(find.text('报告尚未生成'), findsOneWidget);
    expect(find.byType(VoiceComposer), findsNothing);
    expect(find.text('传递作业'), findsNothing);
    await tester.tap(find.text('孩子'));
    await tester.pumpAndSettle();
    expect(find.text('全部孩子'), findsOneWidget);
    expect(find.byType(VoiceComposer), findsNothing);
    await tester.tap(find.byTooltip('孩子操作'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('传递作业'));
    await tester.pumpAndSettle();
    expect(find.text('传递任务'), findsOneWidget);
    expect(find.text('确认传递'), findsOneWidget);
  });

  testWidgets('ordinary tasks and active sessions never pin progress to home',
      (tester) async {
    final api = _MultiPlanWardHomeApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    expect(find.text('今日计划'), findsNothing);
    expect(find.text('未排期任务'), findsNothing);
    expect(find.text('19:00'), findsNothing);
    expect(find.text('数学练习册 P23–25'), findsNothing);
    expect(find.text('进行中'), findsNothing);
    expect(find.byTooltip('更多'), findsOneWidget);
    expect(find.text('作业'), findsNothing);
    expect(find.byTooltip('专注挑战'), findsOneWidget);
  });

  testWidgets('known assignments open on request without inventing time',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(_WardHomeApi())],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await _wardMenu(tester, '作业');
    await tester.pumpAndSettle();
    expect(find.text('已知作业'), findsOneWidget);
    expect(find.text('观察蚂蚁路线'), findsOneWidget);
    expect(find.text('数学练习册'), findsOneWidget);
    expect(find.text('未估时'), findsOneWidget);
    expect(find.text('19:00'), findsNothing);
  });

  testWidgets('ordinary assignment still requires an explicit start',
      (tester) async {
    final api = _WardHomeApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await _wardMenu(tester, '作业');
    await tester.pumpAndSettle();
    await tester.tap(find.text('观察蚂蚁路线'));
    await tester.pumpAndSettle();
    expect(api.startedAssignment, isFalse);
    await tester.tap(find.text('确认开始'));
    await tester.pumpAndSettle();
    expect(api.startedAssignment, isTrue);
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
  });

  testWidgets('active task actions remain available in requested details',
      (tester) async {
    final api = _ActiveTaskApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    expect(find.text('进行中'), findsNothing);
    await _wardMenu(tester, '作业');
    await tester.pumpAndSettle();
    await tester.tap(find.text('观察蚂蚁路线'));
    await tester.pumpAndSettle();
    expect(find.text('这项任务正在进行'), findsOneWidget);
    await tester.tap(find.text('暂停'));
    await tester.pumpAndSettle();
    expect(api.pausedSessionId, 'session-live');
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
  });

  testWidgets('paused task can be resumed without creating a sprint',
      (tester) async {
    final api = _PausedTaskApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await _wardMenu(tester, '作业');
    await tester.pumpAndSettle();
    await tester.tap(find.text('观察蚂蚁路线'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('确认继续'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
  });

  testWidgets('plan can be started from requested details without a fake clock',
      (tester) async {
    final api = _WardHomeApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await _wardMenu(tester, '作业');
    await tester.pumpAndSettle();
    await tester.tap(find.text('数学练习册'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('确认开始'));
    await tester.pumpAndSettle();
    expect(api.startedPlanItem, 'plan-1');
    expect(find.text('19:00'), findsNothing);
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
      'a pronunciation card stays with its reply when a later message is sent',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi();
    final voice = _FakeVoice()..finalText = 'apple';
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

    final asked = tester.getTopLeft(find
        .byKey(const ValueKey('chat-bubble-ward-apple'), skipOffstage: false));
    final card = tester.getTopLeft(find.text('播放', skipOffstage: false));
    expect(card.dy, greaterThan(asked.dy));

    voice.finalText = '谢谢';
    gesture = await tester
        .startGesture(tester.getCenter(find.text('说出你的任何想法、问题、安排')));
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.up();
    await tester.pumpAndSettle();

    expect(find.text('播放', skipOffstage: false), findsOneWidget);
    final cardAfter = tester.getTopLeft(find.text('播放', skipOffstage: false));
    final later = tester.getTopLeft(
        find.byKey(const ValueKey('chat-bubble-ward-谢谢'), skipOffstage: false));
    expect(cardAfter.dy, lessThan(later.dy));
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

    await tester.tap(find.byTooltip('拍照'));
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

  testWidgets('chat image opens full screen and returns to the same bubble',
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
    await tester.tap(find.byTooltip('拍照'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('发送'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('sent-chat-image-0')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat-image-viewer')), findsOneWidget);
    expect(find.byType(InteractiveViewer), findsOneWidget);
    await tester.tap(find.byTooltip('关闭图片'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat-image-viewer')), findsNothing);
    expect(find.byKey(const ValueKey('sent-chat-image-0')), findsOneWidget);
  });

  testWidgets('reloaded historical images open at the tapped page',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi()
      ..currentTranscriptOverride = {
        'thread_id': 'thread-1',
        'thread_version': 1,
        'messages': [
          {
            'id': 'historical-1',
            'thread_id': 'thread-1',
            'thread_version': 1,
            'author_type': 'ward',
            'content': '看看这两张图',
            'attachment_refs': [
              'ward/ward-1/companion/one.png',
              'ward/ward-1/companion/two.png',
            ],
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

    expect(api.imageCalls, ['historical-1:0', 'historical-1:1']);
    await tester.tap(find.byKey(const ValueKey('sent-chat-image-1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat-image-viewer')), findsOneWidget);
    expect(find.text('2/2'), findsOneWidget);
    expect(api.imageCalls, ['historical-1:0', 'historical-1:1']);
    await tester.drag(find.byType(PageView), const Offset(500, 0));
    await tester.pumpAndSettle();
    expect(find.text('1/2'), findsOneWidget);
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
    final ward = tester.getRect(find.byKey(
        const ValueKey('chat-bubble-ward-今晚先读十分钟课外书，然后再做两道数学题，看看时间够不够。')));
    final ai = tester.getRect(find
        .byKey(const ValueKey('chat-bubble-ai-遇到问题随时问我；需要时也可以查看作业，或试一轮专注挑战。')));

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

    await tester.tap(find.byTooltip('拍照'));
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

    await tester.tap(find.byTooltip('拍照'));
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
    await tester.tap(find.byTooltip('拍照'));

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
      ..failOnStartWith = '语音识别暂不可用，请稍后重试'
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
    expect(find.text('语音识别暂不可用，请稍后重试'), findsOneWidget);
  });

  testWidgets('guardian registration sends and submits an email code',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _EmailAuthApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: LoginPage()),
    ));
    await tester.pumpAndSettle();
    expect(find.textContaining('密码'), findsNothing);
    await tester.tap(find.text('没有账号？注册'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextFormField, '姓名'), '妈妈');
    await tester.enterText(
        find.widgetWithText(TextFormField, '邮箱'), 'parent@example.com');
    await tester.tap(find.text('获取验证码'));
    await tester.pump();
    expect(api.sentTo, 'parent@example.com');
    await tester.enterText(
        find.widgetWithText(TextFormField, '邮箱验证码'), '123456');
    await tester.tap(find.text('注册并登录'));
    await tester.pump();
    expect(api.registration, ('妈妈', 'parent@example.com', '123456'));
  });

  testWidgets('sending a replacement code clears the old code input',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _EmailAuthApi();
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: LoginPage()),
    ));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.widgetWithText(TextFormField, '邮箱'), 'parent@example.com');
    await tester.tap(find.text('获取验证码'));
    await tester.pump();
    await tester.enterText(
        find.widgetWithText(TextFormField, '邮箱验证码'), '123456');
    await tester.pump(const Duration(seconds: 60));
    await tester.tap(find.text('获取验证码'));
    await tester.pump();

    expect(api.sentTo, 'parent@example.com');
    expect(find.text('123456'), findsNothing);
  });

  testWidgets(
      'unknown guardian stays on login with a visible registration action',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(_MissingGuardianApi())],
      child: Consumer(
          builder: (context, ref, _) =>
              MaterialApp.router(routerConfig: ref.watch(routerProvider))),
    ));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.widgetWithText(TextFormField, '邮箱'), 'new@example.com');
    await tester.enterText(
        find.widgetWithText(TextFormField, '邮箱验证码'), '123456');
    await tester.tap(find.text('登录'));
    await tester.pumpAndSettle();

    expect(find.text('该邮箱尚未注册，请先注册'), findsOneWidget);
    await tester.tap(find.text('去注册'));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(TextFormField, '姓名'), findsOneWidget);
    expect(find.widgetWithText(TextFormField, '邮箱验证码'), findsOneWidget);
    expect(find.text('123456'), findsOneWidget);
    await tester.enterText(find.widgetWithText(TextFormField, '姓名'), '家长');
    await tester.tap(find.text('注册并登录'));
    await tester.pumpAndSettle();
    expect(find.text('还没有孩子档案'), findsOneWidget);
  });

  testWidgets('ward list shows a readable server error instead of Dio details',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [
        wardsProvider.overrideWith((ref) async {
          final request = RequestOptions(path: '/wards');
          throw DioException(
            requestOptions: request,
            response: Response(requestOptions: request, statusCode: 503),
            type: DioExceptionType.badResponse,
          );
        }),
      ],
      child: const MaterialApp(home: WardListPage()),
    ));
    await tester.pumpAndSettle();

    expect(find.text('加载孩子档案失败：服务暂时不可用，请稍后重试'), findsOneWidget);
    expect(find.textContaining('DioException'), findsNothing);
  });

  testWidgets('invalid email code stays visible beside registration form',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(_InvalidEmailCodeApi())],
      child: Consumer(
          builder: (context, ref, _) =>
              MaterialApp.router(routerConfig: ref.watch(routerProvider))),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('没有账号？注册'));
    await tester.pumpAndSettle();
    await tester.enterText(find.widgetWithText(TextFormField, '姓名'), '家长');
    await tester.enterText(
        find.widgetWithText(TextFormField, '邮箱'), 'parent@example.com');
    await tester.enterText(
        find.widgetWithText(TextFormField, '邮箱验证码'), '123456');
    await tester.tap(find.text('注册并登录'));
    await tester.pumpAndSettle();
    final inlineError = find.descendant(
      of: find.byType(Form),
      matching: find.text('验证码无效或已过期，请重新获取'),
    );
    expect(inlineError, findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
    expect(inlineError, findsOneWidget);
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
    expect(find.byTooltip('更多'), findsOneWidget);
    expect(find.text('作业'), findsNothing);
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

    expect(find.text('传递作业或留言'), findsNothing);
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

    expect(find.text('传递作业或留言'), findsNothing);
    expect(find.text('报告尚未生成'), findsOneWidget);
    await tester.tap(find.text('孩子'));
    await tester.pumpAndSettle();
    expect(find.text('获取绑定码'), findsOneWidget);
  });

  for (final failFirst in [false, true]) {
    testWidgets('clear history confirms, retries and starts fresh ($failFirst)',
        (tester) async {
      FlutterSecureStoragePlatform.instance =
          TestFlutterSecureStoragePlatform({});
      final api = _WardHomeApi()
        ..clearFails = failFirst
        ..currentTranscriptOverride = {
          'thread_id': 'old-thread',
          'thread_version': 2,
          'next_before_thread_version': null,
          'previous_thread_id': 'older-thread',
          'messages': [
            {
              'id': 'old-message',
              'thread_id': 'old-thread',
              'thread_version': 2,
              'author_type': 'companion',
              'content': '需要清空的旧回答',
              'attachment_refs': <String>[]
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
      await _wardMenu(tester, '清空历史对话');
      await tester.pumpAndSettle();
      expect(find.textContaining('历史数据仍由系统保存'), findsOneWidget);
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();
      expect(api.clearCommands, isEmpty);
      expect(find.text('需要清空的旧回答'), findsOneWidget);
      await _wardMenu(tester, '清空历史对话');
      await tester.pumpAndSettle();
      await tester.tap(find.text('清空并重新开始'));
      await tester.pumpAndSettle();
      if (failFirst) {
        expect(find.text('需要清空的旧回答'), findsOneWidget);
        api.clearFails = false;
        await _wardMenu(tester, '清空历史对话');
        await tester.pumpAndSettle();
        await tester.tap(find.text('清空并重新开始'));
        await tester.pumpAndSettle();
        expect(api.clearCommands[0], api.clearCommands[1]);
      }
      expect(find.text('需要清空的旧回答'), findsNothing);
      expect(find.byKey(const Key('load-older-messages-button')), findsNothing);
      expect(await const TokenStorage().companionThreadId, isNull);
      expect(find.text('数学练习册'), findsNothing);
      final send = tester
          .widget<VoiceComposer>(find.byType(VoiceComposer))
          .onVoiceFinal('新问题');
      await tester.pumpAndSettle();
      await send;
      expect(api.submittedThreads.last, isNull);
    });
  }

  testWidgets('clear discards an in-flight older history page', (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final pending = Completer<Map<String, dynamic>>();
    final api = _WardHomeApi()
      ..delayedHistory = pending
      ..currentTranscriptOverride = {
        'thread_id': 'old-thread',
        'thread_version': 2,
        'messages': <dynamic>[],
        'next_before_thread_version': 2,
        'previous_thread_id': null,
      };
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('说出你的任何想法、问题、安排'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('load-older-messages-button')));
    await tester.pump();
    await _wardMenu(tester, '清空历史对话');
    await tester.pump();
    await tester.tap(find.text('清空并重新开始'));
    await tester.pumpAndSettle();
    pending.complete({
      'messages': [
        {
          'id': 'late-history',
          'author_type': 'companion',
          'content': '迟到的历史页面',
          'attachment_refs': <String>[]
        }
      ],
      'next_before_thread_version': 1,
      'previous_thread_id': 'older-thread',
    });
    await tester.pumpAndSettle();
    expect(find.text('迟到的历史页面'), findsNothing);
    expect(find.byKey(const Key('load-older-messages-button')), findsNothing);
  });

  testWidgets('clear during sending discards late reply and thread storage',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final pending = Completer<Map<String, dynamic>>();
    final api = _WardHomeApi()..delayedTurn = pending;
    await tester.pumpWidget(ProviderScope(
      overrides: [apiProvider.overrideWithValue(api)],
      child: const MaterialApp(home: WardDayPage(wardId: 'ward-1')),
    ));
    await tester.pumpAndSettle();
    final send = tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('旧问题');
    await tester.pump();
    await _wardMenu(tester, '清空历史对话');
    await tester.pump();
    await tester.tap(find.text('清空并重新开始'));
    await tester.pumpAndSettle();
    pending.complete({
      'thread_id': 'late-thread',
      'thread_version': 2,
      'interaction': {'kind': 'text', 'content': '迟到的旧回答'}
    });
    await tester.pumpAndSettle();
    await send;
    expect(await const TokenStorage().companionThreadId, isNull);
    expect(find.text('迟到的旧回答'), findsNothing);
    expect(tester.widget<VoiceComposer>(find.byType(VoiceComposer)).enabled,
        isTrue);
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

  testWidgets('plan review card has only the confirm action', (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi()..showPlanSuggestions = true;
    final voice = _FakeVoice()..finalText = '今晚整理错题';
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

    expect(find.textContaining('建议时段为 07:00–22:00'), findsOneWidget);
    expect(find.textContaining('21:25–22:00'), findsOneWidget);
    expect(find.text('确认这个计划'), findsOneWidget);
    expect(find.text('我再改一句'), findsNothing);
    expect(find.byKey(const Key('dismiss-plan-suggestion-duration:task-1')),
        findsNothing);
    expect(find.byKey(const Key('accept-plan-suggestion-time:task-1')),
        findsNothing);
  });

  testWidgets('historical plan review stays before the next question',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi()
      ..currentTranscriptOverride = {
        'thread_id': 'thread-1',
        'thread_version': 4,
        'messages': [
          {
            'id': 'm-1',
            'thread_id': 'thread-1',
            'thread_version': 1,
            'author_type': 'ward',
            'content': '今晚整理错题',
          },
          {
            'id': 'm-2',
            'thread_id': 'thread-1',
            'thread_version': 2,
            'author_type': 'companion',
            'content': '请检查这份计划草稿。',
            'interaction_ref': {
              'kind': 'plan_confirm_list',
              'card_snapshot': {
                'items': [
                  {
                    'title': '整理错题',
                    'planned_minutes': 20,
                    'start_at': '2026-10-25T19:00:00+08:00',
                    'end_at': '2026-10-25T19:20:00+08:00',
                  },
                ],
              },
            },
          },
          {
            'id': 'm-3',
            'thread_id': 'thread-1',
            'thread_version': 3,
            'author_type': 'ward',
            'content': '再问一道题',
          },
          {
            'id': 'm-4',
            'thread_id': 'thread-1',
            'thread_version': 4,
            'author_type': 'companion',
            'content': '我们一步一步看。',
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

    expect(find.text('已记录（待你确认）', skipOffstage: false), findsOneWidget);
    final card = tester.getTopLeft(find.text('已记录（待你确认）', skipOffstage: false));
    final nextQuestion = tester.getTopLeft(find
        .byKey(const ValueKey('chat-bubble-ward-再问一道题'), skipOffstage: false));
    expect(card.dy, lessThan(nextQuestion.dy));
    expect(find.text('确认这个计划', skipOffstage: false), findsNothing);
  });

  testWidgets('current plan review can be confirmed after reopening chat',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi()
      ..currentTranscriptOverride = {
        'thread_id': 'thread-1',
        'thread_version': 2,
        'messages': [
          {
            'id': 'm-1',
            'thread_id': 'thread-1',
            'thread_version': 1,
            'author_type': 'ward',
            'content': '今晚整理错题',
          },
          {
            'id': 'm-2',
            'thread_id': 'thread-1',
            'thread_version': 2,
            'author_type': 'companion',
            'content': '请检查这份计划草稿。',
            'interaction_ref': {
              'kind': 'plan_confirm_list',
              'object_ref': {'object_id': 'draft-1', 'object_version': 2},
              'actions': [
                {
                  'id': 'plan:run:1:draft-1:2',
                  'command': 'confirm_plan',
                  'enabled': true
                },
              ],
              'card_snapshot': {
                'items': [
                  {
                    'title': '整理错题',
                    'planned_minutes': 20,
                    'start_at': '2026-10-25T19:00:00+08:00',
                    'end_at': '2026-10-25T19:20:00+08:00'
                  },
                ],
              },
            },
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

    expect(find.text('已记录（待你确认）'), findsOneWidget);
    expect(find.text('确认这个计划'), findsOneWidget);
    expect(find.textContaining('19:00–19:20'), findsOneWidget);
    await tester.tap(find.text('确认这个计划'));
    await tester.pumpAndSettle();
    expect(api.lastStructuredCommand?['command'], 'confirm_plan');
    expect(api.lastStructuredCommand?['payload'], {
      'draft_id': 'draft-1',
      'expected_draft_version': 2,
    });
  });

  testWidgets('unclear intent shows choices and sends the issued selection',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi()..showIntentChoice = true;
    final voice = _FakeVoice()..finalText = '这些作业怎么处理？';
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

    expect(find.text('管理任务'), findsOneWidget);
    expect(find.text('总结思考'), findsOneWidget);
    expect(find.text('提问探讨'), findsOneWidget);
    await tester.tap(find.byKey(const Key('intent-choice-reflection')));
    await tester.pumpAndSettle();
    expect(api.lastStructuredCommand?['command'], 'choose_intent');
    expect(
        (api.lastStructuredCommand?['payload'] as Map)['intent'], 'reflection');
    expect(api.turns.last.content, '选择：总结思考');
    expect(find.byKey(const Key('intent-choice-reflection')), findsNothing);
  });

  testWidgets('missing duration suggestion uses the clarification action',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi()..suggestMissingDuration = true;
    final voice = _FakeVoice()..finalText = '加一个英语阅读任务';
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
    await tester.ensureVisible(
        find.byKey(const Key('accept-plan-suggestion-clarification:slot-1')));
    await tester.tap(
        find.byKey(const Key('accept-plan-suggestion-clarification:slot-1')));
    await tester.pumpAndSettle();
    expect(api.lastStructuredCommand?['command'], 'clarify_reply');
    final answers =
        (api.lastStructuredCommand?['payload'] as Map)['answers'] as List;
    expect(answers.single['value'], '25分钟');
  });

  testWidgets('clarification still shows time warning without a valid move',
      (tester) async {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    final api = _WardHomeApi()..showClarifyAdvice = true;
    final voice = _FakeVoice()..finalText = '看看时间安排';
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
    expect(find.textContaining('目前没有不冲突的调整时间'), findsOneWidget);
    expect(find.byKey(const Key('accept-plan-suggestion-time:task-1')),
        findsNothing);
  });
  testWidgets(
      'sprint is visible only after explicit start and can hide without stopping',
      (tester) async {
    final api = _SprintApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
    await tester.tap(find.byTooltip('专注挑战'));
    await tester.pumpAndSettle();
    expect(api.creates, 0);
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('数学二十分钟');
    await tester.pumpAndSettle();
    await tester.tap(find.text('开始本轮'));
    await tester.pumpAndSettle();
    expect(api.creates, 1);
    expect(find.byKey(const Key('active-sprint-card')), findsOneWidget);
    expect(find.text('写完了'), findsNothing);
    await tester.tap(find.byTooltip('收起挑战'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
    expect(api.actions, isEmpty);
    await tester.tap(find.byTooltip('专注挑战'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('active-sprint-card')), findsOneWidget);
    await tester.tap(find.text('结束本轮'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
    expect(api.finishedSessionId, isNull);
  });

  for (final status in ['active', 'paused']) {
    for (final source in ['tab', 'chat', 'tasks', 'foreground']) {
      testWidgets('returning from $source restores a hidden $status sprint',
          (tester) async {
        final api = _SprintApi();
        await api.createSprint({'topic': '数学'});
        api.round = {...api.round!, 'status': status};
        await tester.pumpWidget(ProviderScope(
            overrides: [apiProvider.overrideWithValue(api)],
            child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
        await tester.pumpAndSettle();
        if (source == 'chat') await _wardMenu(tester, '历史对话');
        await tester.tap(find.byTooltip('收起挑战'));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('active-sprint-card')), findsNothing);
        switch (source) {
          case 'tab':
            await tester.tap(find.text('成长'));
            await tester.pumpAndSettle();
            await tester.tap(find.text('首页'));
          case 'chat':
            await tester.tap(find.byTooltip('收起对话'));
          case 'tasks':
            await _wardMenu(tester, '作业');
            await tester.tap(find.byTooltip('关闭'));
          case 'foreground':
            tester.binding
                .handleAppLifecycleStateChanged(AppLifecycleState.paused);
            tester.binding
                .handleAppLifecycleStateChanged(AppLifecycleState.resumed);
        }
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('active-sprint-card')), findsOneWidget);
        expect(find.byKey(const Key('companion-chat-list')), findsNothing);
        expect(api.creates, 1);
        expect(api.actions, isEmpty);
      });
    }
  }

  testWidgets('returning home does not restore an ended hidden sprint',
      (tester) async {
    final api = _SprintApi();
    await api.createSprint({'topic': '数学'});
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('收起挑战'));
    await tester.tap(find.text('成长'));
    await tester.pumpAndSettle();
    api.round = null;
    await tester.tap(find.text('首页'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
    expect(find.text('先做手边的一小步'), findsOneWidget);
    expect(api.creates, 1);
    expect(api.actions, isEmpty);
  });

  testWidgets(
      'header countdown keeps ticking when the challenge card is hidden',
      (tester) async {
    final api = _SprintApi();
    await api.createSprint({'topic': '数学'});
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sprint-header-countdown')), findsNothing);
    await tester.pump(const Duration(seconds: 2));
    await tester.tap(find.byTooltip('收起挑战'));
    await tester.pump();
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
    expect(
        tester
            .widget<Text>(find.byKey(const Key('sprint-header-countdown')))
            .data,
        '19:58');
    final headerBounds = tester.getRect(find.descendant(
        of: find.byTooltip('查看专注挑战'), matching: find.byType(TextButton)));
    final clockBounds = tester.getRect(find.descendant(
        of: find.byTooltip('查看专注挑战'),
        matching: find.byIcon(Icons.timer_outlined)));
    final labelBounds =
        tester.getRect(find.byKey(const Key('sprint-header-countdown')));
    expect(clockBounds.top, greaterThanOrEqualTo(headerBounds.top));
    expect(labelBounds.bottom, lessThanOrEqualTo(headerBounds.bottom));
    await tester.pump(const Duration(seconds: 2));
    expect(
        tester
            .widget<Text>(find.byKey(const Key('sprint-header-countdown')))
            .data,
        '19:56');
    await _wardMenu(tester, '历史对话');
    expect(find.byKey(const Key('sprint-header-countdown')), findsOneWidget);
    await tester.tap(find.byTooltip('对话内专注挑战'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('active-sprint-card')), findsOneWidget);
    expect(find.byKey(const Key('sprint-header-countdown')), findsNothing);
    expect(api.creates, 1);
    expect(api.actions, isEmpty);
  });

  testWidgets('header countdown freezes on pause and disappears at expiry',
      (tester) async {
    final api = _SprintApi();
    await api.createSprint({'topic': '数学'});
    api.round = {...api.round!, 'status': 'paused', 'remaining_seconds': 2};
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sprint-header-countdown')), findsNothing);
    await tester.tap(find.byTooltip('收起挑战'));
    await tester.pump(const Duration(seconds: 3));
    expect(
        tester
            .widget<Text>(find.byKey(const Key('sprint-header-countdown')))
            .data,
        '已暂停 · 0:02');
    api.round = {...api.round!, 'status': 'active'};
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('收起挑战'));
    api.round = null;
    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('sprint-header-countdown')), findsNothing);
    expect(api.actions, isEmpty);
  });

  testWidgets('paused header fits a narrow chat with enlarged text',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = _SprintApi();
    await api.createSprint({'topic': '阅读'});
    api.round = {...api.round!, 'status': 'paused'};
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(
            home: MediaQuery(
                data: MediaQueryData(textScaler: TextScaler.linear(1.3)),
                child: WardDayPage(wardId: 'ward-1')))));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('收起挑战'));
    await _wardMenu(tester, '历史对话');
    expect(find.byKey(const Key('sprint-header-countdown')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('failed pause never claims a sprint is paused', (tester) async {
    final api = _SprintApi()..failPause = true;
    await api.createSprint({'topic': '数学'});
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await tester.tap(find.text('暂停本轮'));
    await tester.pumpAndSettle();
    expect(find.text('本轮已暂停'), findsNothing);
    expect(find.text('暂停本轮'), findsOneWidget);
    api.failPause = false;
    await tester.tap(find.text('暂停本轮'));
    await tester.pumpAndSettle();
    expect(find.text('本轮已暂停'), findsOneWidget);
    await tester.tap(find.text('继续本轮'));
    await tester.pumpAndSettle();
    expect(find.text('本轮已暂停'), findsNothing);
  });
  testWidgets('foreground recovery ignores an older in-flight sprint response',
      (tester) async {
    final api = _DelayedSprintApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardDayPage(wardId: 'ward-1'))));
    await tester.pumpAndSettle();
    await api.createSprint({'topic': '新一轮'});
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(find.text('新一轮 · 专注挑战'), findsOneWidget);
    api.firstRead.complete({'sprint': null, 'ready': null});
    await tester.pumpAndSettle();
    expect(find.text('新一轮 · 专注挑战'), findsOneWidget);
  });
}
