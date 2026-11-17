import 'dart:async';

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
  final turns = <({String content, String? state})>[];
  bool fail = false;
  Completer<Map<String, dynamic>>? pending;
  int planReads = 0;
  @override
  Future<Map<String, dynamic>> guardianExperienceTurn(
      {required String content,
      String? stateToken,
      List<String> attachmentKeys = const []}) async {
    turns.add((content: content, state: stateToken));
    if (fail) throw StateError('offline');
    if (pending != null) return pending!.future;
    return {
      'content': '可以先观察共同点，再试着解释。',
      'state_token': 'state-${turns.length}',
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
    {List<Ward> wards = const []}) async {
  await tester.pumpWidget(ProviderScope(overrides: [
    apiProvider.overrideWithValue(api),
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
    await _home(tester, api);
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
    api.pending = null;
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('新问题');
    await tester.pumpAndSettle();
    expect(api.turns.last.state, isNull);
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
                    body: GuardianQuestionPage(
                        active: true, onStartWithChild: () {}))))));
    await tester.pumpAndSettle();
    tester.widget<VoiceComposer>(find.byType(VoiceComposer)).onTap!();
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
