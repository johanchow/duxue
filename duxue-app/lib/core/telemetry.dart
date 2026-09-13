import 'dart:async';
import 'dart:math';

import 'package:dio/dio.dart';
import 'package:flutter/widgets.dart';

typedef AccessTokenProvider = Future<String?> Function();

/// Non-secret build-time settings. Grafana credentials never enter this app.
class TelemetryConfig {
  const TelemetryConfig({
    required this.enabled,
    required this.relayUrl,
    required this.sampleRate,
  });

  factory TelemetryConfig.fromEnvironment(String apiBaseUrl) {
    const configuredUrl = String.fromEnvironment('APP_TELEMETRY_RELAY_URL');
    const enabled = bool.fromEnvironment('APP_TELEMETRY_ENABLED');
    const sampleRateValue = String.fromEnvironment('OTEL_TRACE_SAMPLE_RATE');
    final sampleRate = double.tryParse(sampleRateValue) ?? 0.2;
    return TelemetryConfig(
      enabled: enabled && configuredUrl.isNotEmpty,
      relayUrl: configuredUrl.isEmpty
          ? '$apiBaseUrl/telemetry/client-events'
          : configuredUrl,
      sampleRate: sampleRate.clamp(0, 1).toDouble(),
    );
  }

  final bool enabled;
  final String relayUrl;
  final double sampleRate;
}

/// Generates W3C trace context and batches only whitelisted telemetry metadata.
/// A failed relay request is intentionally ignored: telemetry never blocks UX.
class AppTelemetry {
  AppTelemetry({
    required this.config,
    required this.accessToken,
    Dio? transport,
    Random? random,
  })  : _transport = transport ?? Dio(),
        _random = random ?? Random.secure();

  final TelemetryConfig config;
  final AccessTokenProvider accessToken;
  final Dio _transport;
  final Random _random;
  final List<Map<String, dynamic>> _queue = [];
  bool _flushing = false;

  static const _allowedNames = {
    'app.http',
    'app.auth.refresh',
    'app.report.load',
    'app.device.bind',
    'app.companion.turn',
    'app.asr.session',
    'app.screen.load',
    'app.startup',
    'app.unhandled_error',
    'app.route.view',
  };
  static const _allowedAttributes = {
    'result',
    'route',
    'method',
    'status_class',
    'screen',
    'error_kind',
    'platform',
    'app_version',
    'network_type',
    'report_status',
    'role',
  };

  bool get enabled => config.enabled;
  int get pendingCount => _queue.length;

  TelemetrySpan startSpan(String name, {Map<String, Object?> attributes = const {}}) {
    if (!enabled || !_allowedNames.contains(name)) return TelemetrySpan.disabled();
    return TelemetrySpan._(
      telemetry: this,
      name: name,
      traceId: _hex(16),
      spanId: _hex(8),
      sampled: _random.nextDouble() < config.sampleRate,
      attributes: _safeAttributes(attributes),
    );
  }

  void recordMetric(String name, double value, {Map<String, Object?> attributes = const {}}) {
    _enqueue(name, signal: 'metric', value: value, attributes: attributes);
  }

  void recordEvent(String name, {Map<String, Object?> attributes = const {}}) {
    _enqueue(name, signal: 'event', attributes: attributes);
  }

  void _finish(TelemetrySpan span, Duration duration, Map<String, Object?> attributes) {
    if (!span.sampled) return;
    _enqueue(
      span.name,
      signal: 'span',
      durationMs: duration.inMilliseconds,
      traceId: span.traceId,
      spanId: span.spanId,
      attributes: {...span.attributes, ...attributes},
    );
  }

  void _enqueue(
    String name, {
    required String signal,
    double? value,
    int? durationMs,
    String? traceId,
    String? spanId,
    Map<String, Object?> attributes = const {},
  }) {
    if (!enabled || !_allowedNames.contains(name)) return;
    if (_queue.length >= 100) _queue.removeAt(0);
    _queue.add({
      'signal': signal,
      'name': name,
      if (value != null) 'value': value,
      if (durationMs != null) 'duration_ms': durationMs,
      if (traceId != null) 'trace_id': traceId,
      if (spanId != null) 'span_id': spanId,
      'attributes': _safeAttributes(attributes),
    });
    unawaited(_flush());
  }

  Future<void> _flush() async {
    if (_flushing || _queue.isEmpty || !enabled) return;
    _flushing = true;
    final batch = List<Map<String, dynamic>>.from(_queue.take(20));
    try {
      final token = await accessToken();
      if (token == null) return;
      await _transport.post<void>(
        config.relayUrl,
        data: {'events': batch},
        options: Options(
          headers: {'Authorization': 'Bearer $token'},
          sendTimeout: const Duration(seconds: 2),
          receiveTimeout: const Duration(seconds: 2),
        ),
      );
      _queue.removeRange(0, batch.length);
    } catch (_) {
      // Keep the bounded queue for one later attempt; no user-facing failure.
    } finally {
      _flushing = false;
    }
  }

  Map<String, Object> _safeAttributes(Map<String, Object?> attributes) {
    final result = <String, Object>{};
    attributes.forEach((key, value) {
      if (!_allowedAttributes.contains(key) || value == null) return;
      if (value is String || value is num || value is bool) result[key] = value;
    });
    return result;
  }

  String _hex(int bytes) => List.generate(
        bytes,
        (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0'),
      ).join();

  static String routeTemplate(String path) {
    final uri = Uri.parse(path);
    final segments = uri.pathSegments;
    if (segments.isEmpty) return '/';
    final safe = <String>[];
    for (var index = 0; index < segments.length; index++) {
      final segment = segments[index];
      if (segment.isEmpty) continue;
      final dynamicSegment = index > 0 &&
          (segments[index - 1] == 'wards' ||
              segments[index - 1] == 'devices' ||
              segments[index - 1] == 'plans' ||
              segments[index - 1] == 'sessions' ||
              segments[index - 1] == 'assignments' ||
              segments[index - 1] == 'runs');
      safe.add(dynamicSegment || segment.length > 24 ? ':id' : segment);
    }
    return '/${safe.join('/')}';
  }
}

class TelemetrySpan {
  TelemetrySpan._({
    required this.telemetry,
    required this.name,
    required this.traceId,
    required this.spanId,
    required this.sampled,
    required this.attributes,
  }) : _started = DateTime.now();

  TelemetrySpan.disabled()
      : telemetry = null,
        name = '',
        traceId = '',
        spanId = '',
        sampled = false,
        attributes = const {},
        _started = DateTime.now();

  final AppTelemetry? telemetry;
  final String name;
  final String traceId;
  final String spanId;
  final bool sampled;
  final Map<String, Object> attributes;
  final DateTime _started;
  bool _finished = false;

  String? get traceparent => sampled ? '00-$traceId-$spanId-01' : null;

  void finish({Map<String, Object?> attributes = const {}}) {
    if (_finished || telemetry == null) return;
    _finished = true;
    telemetry!._finish(this, DateTime.now().difference(_started), attributes);
  }
}

class TelemetryRouteObserver extends NavigatorObserver {
  TelemetryRouteObserver(this.telemetry);
  final AppTelemetry telemetry;

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    final name = route.settings.name;
    if (name != null) telemetry.recordEvent('app.route.view', attributes: {'screen': name});
  }
}
