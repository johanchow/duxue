import 'dart:async';
import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/models.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/features/ward_pages.dart';
import 'package:duxue_app/features/guardian_report_view.dart';
import 'package:duxue_app/providers.dart';
import 'package:duxue_app/shared/voice_composer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _ReportApi extends ApiClient {
  _ReportApi()
      : super(baseUrl: 'http://localhost', tokens: const TokenStorage());
  @override
  Future<Map<String, dynamic>> eveningReport(String wardId, DateTime day,
          {int? version}) async =>
      {'status': 'pending'};
  String status = 'ready';
  bool failReport = false;
  bool failEvidence = false;
  bool noEvidence = false;
  final loadedWards = <String>[];
  final loadedDates = <DateTime>[];
  @override
  Future<DailyReport> report(String wardId, DateTime date) async {
    loadedWards.add(wardId);
    loadedDates.add(date);
    if (failReport) throw StateError('offline');
    return DailyReport(
        status: status,
        date: date,
        totalSeconds: 600,
        breakdown: {'学习': 600},
        timeline: const [],
        profileChanged: false);
  }

  @override
  Future<List<Map<String, dynamic>>> tutoringEvidence(
      String wardId, DateTime day) async {
    if (failEvidence) throw StateError('offline');
    if (noEvidence) return [];
    return [
      {
        'id': '$wardId-problem',
        'title': '$wardId 分数应用题',
        'status': 'submitted',
        'basis': 'guided_student_attempts'
      }
    ];
  }

  @override
  Future<Map<String, dynamic>> tutoringEvidenceDetail(
          String wardId, DateTime day, String id) async =>
      {
        'id': id,
        'messages': [
          {
            'id': 'guide',
            'role': 'assistant',
            'kind': 'guide',
            'content': '先比较两个数量的关系。'
          },
          {
            'id': 'attempt',
            'role': 'ward',
            'kind': 'attempt',
            'content': '我先画图，再自己列式。'
          },
        ]
      };
}

class _DelayedReportApi extends _ReportApi {
  final pending = Completer<DailyReport>();
  @override
  Future<DailyReport> report(String wardId, DateTime date) {
    if (wardId == 'ward-1') return pending.future;
    return super.report(wardId, date);
  }
}

Future<void> _home(WidgetTester tester, _ReportApi api,
    {bool settle = true}) async {
  await tester.pumpWidget(ProviderScope(overrides: [
    apiProvider.overrideWithValue(api),
    wardsProvider.overrideWith((ref) async => const [
          Ward(id: 'ward-1', displayName: '小宇', gradeStage: 'primary'),
          Ward(id: 'ward-2', displayName: '小雨', gradeStage: 'primary'),
        ])
  ], child: const MaterialApp(home: WardListPage())));
  if (settle) {
    await tester.pumpAndSettle();
  } else {
    await tester.pump();
    await tester.pump();
  }
}

void main() {
  testWidgets(
      'guardian defaults to a readable report and inline thinking process',
      (tester) async {
    final api = _ReportApi();
    await _home(tester, api);
    expect(find.text('学习报告'), findsOneWidget);
    expect(find.textContaining('10分钟'), findsOneWidget);
    expect(find.text('查看完整报告'), findsNothing);
    expect(find.text('可能需要你的支持'), findsNothing);
    expect(find.byType(VoiceComposer), findsNothing);
    expect(find.byType(TextField), findsNothing);
    expect(find.text('独立解题凭证'), findsOneWidget);
    expect(find.text('先比较两个数量的关系。'), findsNothing);
    await tester.tap(find.text('展开思考过程'));
    await tester.pumpAndSettle();
    expect(find.text('先比较两个数量的关系。'), findsOneWidget);
    expect(find.text('我先画图，再自己列式。'), findsOneWidget);
    expect(find.textContaining('已掌握'), findsNothing);
  });

  testWidgets(
      'pending report never blocks existing evidence or asks for a self-review',
      (tester) async {
    await _home(tester, _ReportApi()..status = 'empty');
    expect(find.text('报告尚未生成'), findsOneWidget);
    expect(find.text('独立解题凭证'), findsOneWidget);
    expect(find.textContaining('完成自我总结'), findsNothing);
    expect(find.text('查看完整报告'), findsNothing);
  });

  testWidgets(
      'report failure is distinct from pending and can retry independently',
      (tester) async {
    final api = _ReportApi()..failReport = true;
    await _home(tester, api);
    expect(find.text('报告加载失败'), findsOneWidget);
    expect(find.text('报告尚未生成'), findsNothing);
    expect(find.text('独立解题凭证'), findsOneWidget);
    api.failReport = false;
    await tester.tap(find.text('重试报告'));
    await tester.pumpAndSettle();
    expect(find.text('报告加载失败'), findsNothing);
    expect(find.textContaining('10分钟'), findsOneWidget);
  });

  testWidgets(
      'switching ward replaces report and credentials without leaking the previous child',
      (tester) async {
    final api = _ReportApi();
    await _home(tester, api);
    await tester.tap(find.text('小宇'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('小雨').last);
    await tester.pumpAndSettle();
    expect(api.loadedWards.last, 'ward-2');
    expect(find.text('ward-1 分数应用题'), findsNothing);
    expect(find.text('ward-2 分数应用题'), findsOneWidget);
  });
  testWidgets(
      'processing is distinct and missing credentials leave no empty section',
      (tester) async {
    await _home(
        tester,
        _ReportApi()
          ..status = 'processing'
          ..noEvidence = true);
    expect(find.text('正在整理学习报告'), findsOneWidget);
    expect(find.text('报告尚未生成'), findsNothing);
    expect(find.text('独立解题凭证'), findsNothing);
  });

  testWidgets(
      'evidence failure is retryable and does not hide the ready report',
      (tester) async {
    final api = _ReportApi()..failEvidence = true;
    await _home(tester, api);
    expect(find.text('解题凭证加载失败'), findsOneWidget);
    expect(find.textContaining('10分钟'), findsOneWidget);
    api.failEvidence = false;
    await tester.tap(find.text('重试凭证'));
    await tester.pumpAndSettle();
    expect(find.text('解题凭证加载失败'), findsNothing);
    expect(find.text('独立解题凭证'), findsOneWidget);
  });

  testWidgets('history selects the same date for report and thinking evidence',
      (tester) async {
    final api = _ReportApi();
    await _home(tester, api);
    final yesterday = guardianToday().subtract(const Duration(days: 1));
    await tester.tap(find.text('历史'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Switch to input'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField),
        '${yesterday.month}/${yesterday.day}/${yesterday.year}');
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    expect(api.loadedDates.last, yesterday);
    expect(find.text('${yesterday.month}月${yesterday.day}日'), findsOneWidget);
  });

  testWidgets('a late report cannot overwrite the newly selected child',
      (tester) async {
    final api = _DelayedReportApi();
    await _home(tester, api, settle: false);
    await tester.tap(find.text('小宇'));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.text('小雨').last);
    await tester.pumpAndSettle();
    api.pending.complete(DailyReport(
        status: 'ready',
        date: guardianToday(),
        totalSeconds: 600,
        breakdown: const {'旧孩子活动': 600},
        timeline: const [],
        profileChanged: false));
    await tester.pumpAndSettle();
    expect(find.textContaining('旧孩子活动'), findsNothing);
    expect(find.text('ward-2 分数应用题'), findsOneWidget);
  });
}
