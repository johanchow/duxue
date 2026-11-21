import 'dart:async';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:dio/dio.dart';
import 'package:duxue_app/core/conversation_latency.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('a lost acknowledgement survives restart and replays the same event',
      () async {
    FlutterSecureStorage.setMockInitialValues({});
    final delivered = <Map<String, dynamic>>[];
    final firstAttempt = Completer<void>();
    final client = Dio()
      ..interceptors.add(InterceptorsWrapper(onRequest: (request, handler) {
        delivered.add(
            Map<String, dynamic>.from(request.data['events'].single as Map));
        if (delivered.length == 1) {
          handler.reject(DioException(
              requestOptions: request, type: DioExceptionType.receiveTimeout));
          firstAttempt.complete();
        } else {
          handler.resolve(Response(
              requestOptions: request, data: {'accepted': 1}, statusCode: 202));
        }
      }));
    ConversationLatency open() => ConversationLatency(
        'https://example.invalid/telemetry/client-events',
        () async => 'test-token',
        client: client);
    final first = open();
    first.start('guardian').finish('success');
    await firstAttempt.future;
    first.dispose();
    final second = open();
    await second.restore();
    expect(delivered, hasLength(2));
    expect(delivered.first, delivered.last);
    expect(await const FlutterSecureStorage().readAll(), isEmpty);
    second.dispose();
  });

  for (final role in ['guardian', 'ward']) {
    test('$role retains a single terminal event and request trace', () async {
      final records = <Map<String, dynamic>>[];
      final turn = ConversationTurn(role, 'turn', records.add);
      await turn.request(() async {
        expect(ConversationTurn.current, same(turn));
        turn.traceId = 'trace';
      });
      turn.finish('success');
      turn.finish('cancelled');
      expect(records.single['trace_id'], 'trace');
      expect(records.single['attributes'], {'role': role, 'result': 'success'});
      expect(records.single['duration_ms'], greaterThanOrEqualTo(0));
    });
  }
  for (final pair in [
    (DioExceptionType.receiveTimeout, 'timeout'),
    (DioExceptionType.cancel, 'cancelled'),
    (DioExceptionType.badResponse, 'error')
  ]) {
    test('classifies ${pair.$1}', () {
      final records = <Map<String, dynamic>>[];
      ConversationTurn('ward', 'turn', records.add)
          .fail(DioException(requestOptions: RequestOptions(), type: pair.$1));
      expect(records.single['attributes']['result'], pair.$2);
    });
  }
}
