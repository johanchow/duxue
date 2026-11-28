import 'dart:async';
import 'dart:typed_data';
import 'package:duxue_app/core/speech_playback.dart';
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
      'tutoring': {'verified_count': 0},
      'creation_footprints': [if (version == null) {'title': '水循环绘本'}],
      'observation': {
        'totals': {'unknown': 60},
        'coverage': {'ratio': null}
      }
    };
  }
}

class _Playback implements SpeechPlayback {
  final completed = StreamController<void>.broadcast();
  int plays = 0;
  @override
  Stream<void> get onComplete => completed.stream;
  @override
  Future<void> playStream(Stream<List<int>> frames) async {
    final bytes = BytesBuilder();
    await for (final frame in frames) { bytes.add(frame); }
    await playMp3(bytes.takeBytes());
  }

  @override
  Future<void> playMp3(Uint8List bytes) async {
    plays++;
  }

  @override
  Future<void> stop() async {}
  @override
  Future<void> dispose() => completed.close();
  @override
  Future<void> speak(String text, String locale) => throw UnimplementedError();
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
    expect(find.text('今日无可核验答疑'), findsOneWidget);
    expect(find.text('水循环绘本'), findsOneWidget);
    expect(find.text('无法判断：约 1 分钟'), findsOneWidget);
    await tester.tap(find.byType(DropdownButton<int>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('第 1 版').last);
    await tester.pumpAndSettle();
    expect(api.versions, [null, 1]);
    expect(find.text('水循环绘本'), findsNothing);
    expect(find.text('晚间实况 · 第 1 版'), findsOneWidget);
  });

  for (final prompt in ['invite_return', 'offer_help']) {
    testWidgets('$prompt automatically speaks once without rendering a card',
        (tester) async {
      final api = ReportApi();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      tester.binding.defaultBinaryMessenger.setMockMessageHandler(
        'flutter/assets',
        (_) async => ByteData(32),
      );
      addTearDown(() => tester.binding.defaultBinaryMessenger
          .setMockMessageHandler('flutter/assets', null));
      final playback = _Playback();
      final paths = <String>[];
      api.dio.interceptors.insert(0,
          InterceptorsWrapper(onRequest: (options, handler) {
        paths.add(options.path);
        Object data;
        if (options.path.endsWith('/receipts')) {
          expect(options.data['medium'], 'speech_completed');
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
              'prompt_id': prompt
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
                  body: SupportCompanionPanel(
                      wardId: 'ward', playback: () => playback)))));
      await tester.pumpAndSettle();
      expect(find.text('这题需要一点提示吗？'), findsNothing);
      expect(playback.plays, 1, reason: paths.toString());
      expect(paths.where((p) => p.endsWith('/receipts')), isEmpty);
      playback.completed.add(null);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 1));
      expect(paths.where((p) => p.endsWith('/receipts')).length, 1);
      await tester.pump(const Duration(seconds: 15));
      expect(playback.plays, 1, reason: paths.toString());
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      final before = paths.where((p) => p.endsWith('/offer')).length;
      await tester.pump(const Duration(seconds: 30));
      expect(paths.where((p) => p.endsWith('/offer')).length, before);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      await tester.pumpWidget(const SizedBox());
    });
  }
}
