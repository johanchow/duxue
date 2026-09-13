import 'dart:math';

import 'package:duxue_app/core/telemetry.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  AppTelemetry enabledTelemetry() => AppTelemetry(
        config: const TelemetryConfig(
          enabled: true,
          relayUrl: 'https://example.invalid/telemetry/client-events',
          sampleRate: 1,
        ),
        accessToken: () async => null,
        random: Random(1),
      );

  test('W3C traceparent is generated without any credential', () {
    final span = enabledTelemetry().startSpan('app.http');
    expect(span.traceparent, matches(RegExp(r'^00-[0-9a-f]{32}-[0-9a-f]{16}-01$')));
  });

  test('route templates remove dynamic ward identifiers and query data', () {
    expect(
      AppTelemetry.routeTemplate('/wards/ward-secret-123/report?date=2026-09-13'),
      '/wards/:id/report',
    );
  });

  test('unsupported names and sensitive attribute keys are not queued', () {
    final telemetry = enabledTelemetry();
    telemetry.recordEvent('app.unknown', attributes: {'content': 'private text'});
    telemetry.recordEvent('app.report.load', attributes: {
      'content': 'private text',
      'ward_id': 'ward-secret',
      'result': 'success',
    });
    expect(telemetry.pendingCount, 1);
  });

  test('disabled telemetry produces neither spans nor relay events', () {
    final telemetry = AppTelemetry(
      config: const TelemetryConfig(enabled: false, relayUrl: '', sampleRate: 0),
      accessToken: () async => null,
    );
    expect(telemetry.startSpan('app.http').traceparent, isNull);
    telemetry.recordEvent('app.report.load', attributes: {'result': 'success'});
    expect(telemetry.pendingCount, 0);
  });
}
