import 'package:dio/dio.dart';
import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/features/evening_report_card.dart';
import 'package:duxue_app/features/support_companion_panel.dart';
import 'package:duxue_app/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

class ReportApi extends ApiClient {
  ReportApi()
      : super(baseUrl: 'http://localhost', tokens: const TokenStorage());
  final versions = <int?>[];
  @override
  Future<Map<String, dynamic>> eveningReport(String wardId, DateTime day,
      {int? version}) async {
    versions.add(version);
    return {
      'status': 'partial',
      'version': version ?? 2,
      'summary': '观察证据不足',
      'cutoff_at': '21:30',
      'observation': {
        'totals': {'unknown': 60},
        'coverage': {'ratio': null}
      }
    };
  }
}

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));
  testWidgets(
      'report distinguishes unknown coverage and selects immutable history',
      (tester) async {
    final api = ReportApi();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: MaterialApp(
            home: Scaffold(
                body: EveningReportCard(
                    wardId: 'ward', date: DateTime(2026, 11, 12))))));
    await tester.pumpAndSettle();
    expect(find.text('采集覆盖率暂不可确定'), findsOneWidget);
    expect(find.text('无法判断：约 1 分钟'), findsOneWidget);
    await tester.tap(find.byType(DropdownButton<int>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('第 1 版').last);
    await tester.pumpAndSettle();
    expect(api.versions, [null, 1]);
    expect(find.text('晚间实况 · 第 1 版'), findsOneWidget);
  });

  testWidgets(
      'support stays silent until opt-in and expires a rendered invitation',
      (tester) async {
    final api = ReportApi();
    final paths = <String>[];
    api.dio.interceptors.insert(0,
        InterceptorsWrapper(onRequest: (options, handler) {
      paths.add(options.path);
      Object data;
      if (options.path.endsWith('/receipts')) {
        data = {'version': 2, 'status': 'presented'};
      } else if (options.path.endsWith('/offer')) {
        data = {
          'offer': {
            'offer_id': 'fixture',
            'version': 1,
            'protocol_version': 'support.v1',
            'expires_at': DateTime.now()
                .add(const Duration(seconds: 2))
                .toIso8601String(),
            'text': '这题需要一点提示吗？',
            'prompt_id': 'offer_help'
          }
        };
      } else {
        data = {'id': 'channel'};
      }
      handler.resolve(
          Response(requestOptions: options, statusCode: 200, data: data));
    }));
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: MaterialApp(
            home: Scaffold(
                body: SupportCompanionPanel(wardId: 'ward', onAsk: () {})))));
    await tester.pump(const Duration(seconds: 16));
    expect(paths, isEmpty);
    await tester.tap(find.text('开启陪伴提示'));
    await tester.pumpAndSettle();
    expect(find.text('这题需要一点提示吗？'), findsOneWidget);
    expect(paths.where((p) => p.endsWith('/receipts')).length, 1);
    await tester.pump(const Duration(seconds: 3));
    expect(find.text('这题需要一点提示吗？'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
