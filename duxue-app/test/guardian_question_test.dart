import 'dart:async';
import 'recording_conversation_latency.dart';

import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/models.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/features/guardian_question_page.dart';
import 'package:duxue_app/features/guardian_report_view.dart';
import 'package:duxue_app/features/ward_pages.dart';
import 'package:duxue_app/providers.dart';
import 'package:duxue_app/shared/voice_composer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://localhost', tokens: const TokenStorage());
  final turns = <({String content, String? state, String mode, List<String> keys})>[];
  bool fail = false;
  Completer<Map<String, dynamic>>? pending;
  void Function(String)? stageListener;
  int planReads = 0;
  @override
  Future<Map<String, dynamic>> guardianExperienceTurn(
      {required String content,
      String? stateToken,
      List<String> attachmentKeys = const [],
      String mode = 'student_guide', void Function(String)? onStage}) async {
    stageListener = onStage;
    if (mode == 'guardian_explain') onStage?.call('read');
    turns.add((content: content, state: stateToken, mode: mode, keys: attachmentKeys));
    if (fail) throw StateError('offline');
    if (pending != null) return pending!.future;
    if (mode == 'guardian_explain') {
      return {
        'mode': 'guardian_explain',
        'act': 'explain',
        'content': '【考点与题眼】通分找最小公倍数 12。\n【完整破题思路】9/12 > 8/12，故 3/4 > 2/3。',
        'state_token': 'mentor-state-${turns.length}',
        'verification': {'status': 'ready', 'confidence': 'high'},
        'recommend_courseware': true,
      };
    }
    return {
      'mode': 'student_guide',
      'content': '可以先观察共同点，再试着解释。',
      'state_token': 'state-${turns.length}',
      'turn_id': 'turn-${turns.length}',
      'mentor_origin_turn_id': 'turn-1',
      'mentor_start_token': 'topic-${turns.length}',
      'visual': {
        'kind': 'compare',
        'title': '观察关系',
        'alt': '对比左右两侧的特征',
        'columns': [
          {
            'title': '左边',
            'items': ['第一个特征']
          },
          {
            'title': '右边',
            'items': ['第二个特征']
          },
        ]
      }
    };
  }

  @override
  Future<Map<String, dynamic>> eveningReport(String wardId, DateTime date,
          {int? version}) async =>
      {'status': 'pending'};
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
          String wardId, DateTime day) async =>
      [];
  @override
  Future<Map<String, dynamic>> plan(String wardId, DateTime day) async {
    planReads++;
    throw StateError('must not read plan');
  }

  @override
  Future<List<dynamic>> assignments(String wardId) async {
    planReads++;
    throw StateError('must not read assignments');
  }
}

Future<void> _home(WidgetTester tester, _Api api,
    {List<Ward> wards = const [], RecordingConversationLatency? latency}) async {
  await tester.pumpWidget(ProviderScope(overrides: [
    apiProvider.overrideWithValue(api),
    if (latency != null) conversationLatencyProvider.overrideWithValue(latency),
    wardsProvider.overrideWith((ref) async => wards)
  ], child: const MaterialApp(home: WardListPage())));
  await tester.pumpAndSettle();
}

Future<void> _tab(WidgetTester tester, String label) async {
  await tester.tap(find.descendant(
      of: find.byType(NavigationBar), matching: find.text(label)));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('mentor stages stay with their in-flight conversation',
      (tester) async {
    final api = _Api()..pending = Completer();
    await _home(tester, api);
    await _tab(tester, '问答');
    await tester.tap(find.byKey(const ValueKey('mode-guardian_explain')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('用一道示例题'));
    await tester.pump();
    expect(find.text('正在识别题面…'), findsNothing);
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.text('正在识别题面…'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);

    final stage = api.stageListener!;
    stage('solve');
    stage('solve');
    stage('unknown');
    await tester.pump();
    expect(find.text('正在推导解题思路…'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('mode-student_guide')));
    await tester.pumpAndSettle();
    stage('explain');
    await tester.pump();
    expect(find.text('正在整理导师讲解…'), findsNothing);

    await tester.tap(find.byKey(const ValueKey('mode-guardian_explain')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.text('正在整理导师讲解…'), findsOneWidget);
    api.pending!.complete({'content': '导师回复'});
    await tester.pumpAndSettle();
    expect(find.text('正在整理导师讲解…'), findsNothing);
    expect(find.text('导师回复'), findsOneWidget);
  });

  testWidgets('student reply failure replaces its waiting status with retry',
      (tester) async {
    final api = _Api()..pending = Completer();
    await _home(tester, api);
    await _tab(tester, '问答');
    await tester.tap(find.text('用一道示例题'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.text('正在准备回复…'), findsOneWidget);
    api.stageListener!('draft');
    await tester.pump();
    expect(find.text('正在整理怎么一步步讲…'), findsOneWidget);
    api.pending!.completeError(StateError('offline'));
    await tester.pumpAndSettle();
    expect(find.text('正在准备回复…'), findsNothing);
    expect(find.text('重试'), findsOneWidget);
  });

  testWidgets('a reply arriving while reading history preserves the scroll',
      (tester) async {
    final api = _Api()..pending = Completer();
    await _home(tester, api);
    await _tab(tester, '问答');
    await tester.tap(find.text('用一道示例题'));
    await tester.pumpAndSettle();
    api.pending!.complete({
      'content': List.filled(35, '这是一条历史回复。').join('\n\n'),
    });
    await tester.pumpAndSettle();
    api.pending = Completer();
    unawaited(tester.widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('下一题'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    await tester.pumpAndSettle();

    final questionLists = find.descendant(
      of: find.byType(GuardianQuestionPage),
      matching: find.byType(ListView),
    );
    final scroll = tester.widget<ListView>(questionLists.first).controller!;
    expect(scroll.position.maxScrollExtent, greaterThan(200));
    scroll.jumpTo(60);
    api.pending!.complete({'content': '新回复'});
    await tester.pumpAndSettle();
    expect(scroll.offset, 60);
    expect(find.text('正在准备回复…'), findsNothing);
  });

  testWidgets('empty modes offer the same opt-in example and no invite prompt',
      (tester) async {
    final api = _Api();
    await _home(tester, api);
    await _tab(tester, '问答');

    final studentMode = find.text('体验孩子怎么学');
    final mentorMode = find.text('看导师怎么讲');
    final example = find.text('用一道示例题');

    expect(studentMode, findsOneWidget);
    expect(mentorMode, findsOneWidget);
    expect(example, findsOneWidget);
    expect(find.text('问个知识点'), findsNothing);
    expect(find.text('听听发音'), findsNothing);
    expect(api.turns, isEmpty);

    await tester.tap(example);
    await tester.pumpAndSettle();
    final mentorTurn = api.turns.single;
    expect(mentorTurn.mode, 'guardian_explain');
    expect(example, findsNothing);
    expect(find.text('生成深度课件'), findsOneWidget);
    expect(find.text('让孩子也试试'), findsNothing);

    await tester.tap(studentMode);
    await tester.pumpAndSettle();
    expect(example, findsOneWidget);
    expect(find.text('看分数比较讲题教案'), findsNothing);
    expect(api.turns, hasLength(1));
    await tester.tap(example);
    await tester.pumpAndSettle();
    expect(api.turns.last.mode, 'student_guide');
    expect(api.turns.last.content, mentorTurn.content);
    expect(example, findsNothing);
    expect(find.text('看这道题的完整讲解'), findsOneWidget);
    expect(find.text('让孩子也试试'), findsNothing);
  });

  testWidgets(
      'Android back from questions returns to children and preserves the draft',
      (tester) async {
    await _home(tester, _Api());
    await _tab(tester, '问答');
    tester.widget<VoiceComposer>(find.byType(VoiceComposer)).onTap!();
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '还没发送的问题');
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(
        tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
        0);
    await _tab(tester, '问答');
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '还没发送的问题');
  });
  testWidgets(
      'adult can ask without a child and navigation preserves independent conversation',
      (tester) async {
    final api = _Api();
    await _home(tester, api);
    await _tab(tester, '问答');
    await tester.tap(find.byKey(const ValueKey('mode-student_guide')));
    await tester.pumpAndSettle();
    expect(find.byType(VoiceComposer), findsOneWidget);
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('为什么月亮会有圆缺？');
    await tester.pumpAndSettle();
    expect(api.turns.single.state, isNull);
    expect(find.text('观察关系'), findsOneWidget);
    expect(find.text('第一个特征'), findsOneWidget);
    expect(find.text('可以先观察共同点，再试着解释。'), findsOneWidget);
    await _tab(tester, '我的');
    expect(find.byType(VoiceComposer, skipOffstage: false), findsNothing);
    await _tab(tester, '问答');
    expect(find.text('可以先观察共同点，再试着解释。'), findsOneWidget);
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('我还是不懂');
    await tester.pumpAndSettle();
    expect(api.turns.last.state, 'state-1');
    expect(api.planReads, 0);
  });

  testWidgets('typing retries the same draft without duplicate messages',
      (tester) async {
    final api = _Api()..fail = true;
    await _home(tester, api);
    await _tab(tester, '问答');
    tester.widget<VoiceComposer>(find.byType(VoiceComposer)).onTap!();
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '如何理解通分？');
    await tester.tap(find.byTooltip('发送问题'));
    await tester.pumpAndSettle();
    expect(find.text('这次没能发送成功，请重试。'), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '如何理解通分？');
    api.fail = false;
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    expect(find.text('这次没能发送成功，请重试。'), findsNothing);
    expect(find.text('如何理解通分？'), findsOneWidget);
    expect(api.turns.map((turn) => turn.content), ['如何理解通分？', '如何理解通分？']);
  });

  testWidgets(
      'clear rejects a late response and the next turn starts with no state',
      (tester) async {
    final api = _Api()..pending = Completer();
    final latency = RecordingConversationLatency();
    await _home(tester, api, latency: latency);
    await _tab(tester, '问答');
    final sending = tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('旧问题');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.byTooltip('重新开始问答'));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.widgetWithText(TextButton, '重新开始'));
    await tester.pumpAndSettle();
    api.pending!.complete({'content': '迟到的回复', 'state_token': 'old'});
    await sending;
    await tester.pumpAndSettle();
    expect(find.text('迟到的回复'), findsNothing);
    expect(latency.events.single['attributes']['result'], 'cancelled');
    api.pending = null;
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('新问题');
    await tester.pumpAndSettle();
    expect(api.turns.last.state, isNull);
    expect(latency.events.last['attributes'], {'result': 'success', 'role': 'guardian'});
    expect(latency.events.length, 2);
  });

  testWidgets(
      'single child reads report directly while multiple children open a report in one tap',
      (tester) async {
    final api = _Api();
    await _home(tester, api,
        wards: const [Ward(id: '1', displayName: '小宇', gradeStage: 'primary')]);
    expect(find.byType(GuardianReportView), findsOneWidget);
    expect(find.text('今日计划'), findsNothing);
    expect(api.planReads, 0);
    await tester.pumpWidget(const SizedBox.shrink());
    await _home(tester, api, wards: const [
      Ward(id: '1', displayName: '小宇', gradeStage: 'primary'),
      Ward(id: '2', displayName: '小雨', gradeStage: 'primary')
    ]);
    expect(find.byType(GuardianReportView), findsNothing);
    await tester.tap(find.text('小雨'));
    await tester.pumpAndSettle();
    expect(
        tester
            .widget<GuardianReportView>(find.byType(GuardianReportView))
            .wardId,
        '2');
    expect(find.byType(NavigationBar), findsOneWidget);
    await tester.tap(find.byTooltip('全部孩子'));
    await tester.pumpAndSettle();
    expect(find.text('小宇'), findsOneWidget);
    expect(api.planReads, 0);
  });

  testWidgets('legacy child route opens report without plan requests',
      (tester) async {
    final api = _Api();
    await tester.pumpWidget(ProviderScope(overrides: [
      apiProvider.overrideWithValue(api),
      wardsProvider.overrideWith((ref) async => const [])
    ], child: const MaterialApp(home: WardDetailPage(wardId: '1'))));
    await tester.pumpAndSettle();
    expect(find.byType(GuardianReportView), findsOneWidget);
    expect(find.text('今日计划'), findsNothing);
    expect(api.planReads, 0);
  });

  testWidgets(
      'question page fits a narrow screen with large text and keyboard inset',
      (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(_Api())],
        child: MaterialApp(
            home: MediaQuery(
                data: const MediaQueryData(
                    size: Size(320, 640),
                    textScaler: TextScaler.linear(1.4),
                    viewInsets: EdgeInsets.only(bottom: 250)),
                child: Scaffold(
                    body: GuardianQuestionPage(active: true))))));
    await tester.pumpAndSettle();
    tester.widget<VoiceComposer>(find.byType(VoiceComposer)).onTap!();
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'dual perspective keeps isolated state tokens and supports one-tap mentor reveal',
      (tester) async {
    final api = _Api();
    await _home(tester, api);
    await _tab(tester, '问答');

    // 1. Switch to student_guide (default is now guardian_explain)
    await tester.tap(find.byKey(const ValueKey('mode-student_guide')));
    await tester.pumpAndSettle();
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('比较 3/4 和 2/3');
    await tester.pumpAndSettle();
    expect(api.turns.single.mode, 'student_guide');
    expect(api.turns.single.state, isNull);
    expect(find.text('看这道题的完整讲解'), findsOneWidget);

    // 2. One-tap reveal switches to guardian_explain with the signed topic start token and preserves student stateToken
    await tester.tap(find.text('看这道题的完整讲解'));
    await tester.pumpAndSettle();
    expect(api.turns.last.mode, 'guardian_explain');
    expect(api.turns.last.content, '比较 3/4 和 2/3');
    expect(api.turns.last.state, 'topic-1');
    expect(find.textContaining('【完整破题思路】'), findsOneWidget);

    // 3. Follow-up in guardian_explain uses mentor-state-2, then switching back to student视角 restores student session & state-1
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('孩子通分容易错哪？');
    await tester.pumpAndSettle();
    expect(api.turns.last.mode, 'guardian_explain');
    expect(api.turns.last.state, 'mentor-state-2');

    await tester.tap(find.byKey(const ValueKey('mode-student_guide')));
    await tester.pumpAndSettle();
    expect(find.text('可以先观察共同点，再试着解释。'), findsOneWidget);
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('公分母是12');
    await tester.pumpAndSettle();
    expect(api.turns.last.mode, 'student_guide');
    expect(api.turns.last.state, 'state-1');
    await tester.tap(find.text('看这道题的完整讲解'));
    await tester.pumpAndSettle();
    expect(api.turns.last.content, '比较 3/4 和 2/3');
    expect(api.turns.last.state, 'topic-4');
  });

  testWidgets(
      'switching perspectives preserves each draft and clearing mentor does not wipe student thread',
      (tester) async {
    final api = _Api();
    await _home(tester, api);
    await _tab(tester, '问答');

    // Send one message in student视角 and type an unsent draft
    await tester.tap(find.byKey(const ValueKey('mode-student_guide')));
    await tester.pumpAndSettle();
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('第一题');
    await tester.pumpAndSettle();
    tester.widget<VoiceComposer>(find.byType(VoiceComposer)).onTap!();
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '学生草稿');

    // Switch to 导师视角: input starts empty, type mentor draft, send a pending mentor turn, then clear mentor
    await tester.tap(find.byKey(const ValueKey('mode-guardian_explain')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, '');
    api.pending = Completer();
    await tester.enterText(find.byType(TextField), '导师问题');
    await tester.tap(find.byTooltip('发送问题'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('正在识别题面…'), findsOneWidget);
    await tester.tap(find.byTooltip('重新开始问答'));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.widgetWithText(TextButton, '重新开始'));
    await tester.pumpAndSettle();
    api.pending!.complete({'content': '迟到的导师回复', 'state_token': 'stale-mentor'});
    await tester.pumpAndSettle();
    expect(find.text('迟到的导师回复'), findsNothing);
    expect(find.text('正在识别题面…'), findsNothing);

    // Switch back to 学生视角: student history and unsent draft are completely intact!
    await tester.tap(find.byKey(const ValueKey('mode-student_guide')));
    await tester.pumpAndSettle();
    expect(find.text('可以先观察共同点，再试着解释。'), findsOneWidget);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '学生草稿');
  });
}
