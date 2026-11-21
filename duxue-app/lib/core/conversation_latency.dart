import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// One terminal event per send. The HTTP interceptor associates the business
/// request with this turn while preserving the existing trace sampling policy.
class ConversationTurn {
  ConversationTurn(this.entry, this.id, this._record);
  final String entry, id;
  final void Function(Map<String, dynamic>) _record;
  final _clock = Stopwatch()..start();
  String? traceId;
  static ConversationTurn? get current => Zone.current[ConversationTurn];

  Future<T> request<T>(Future<T> Function() call) =>
      runZoned(call, zoneValues: {ConversationTurn: this});

  void fail(Object error) {
    final response = error is DioException ? error.response : null;
    final mentorTimeout = switch (response?.data) {
      {'detail': {'code': 'mentor_timeout'}} => true,
      _ => false,
    };
    if (response?.statusCode == 408 ||
        response?.statusCode == 504 ||
        mentorTimeout) {
      finish('timeout');
      return;
    }
    final type = error is DioException ? error.type : null;
    finish(switch (type) {
      DioExceptionType.receiveTimeout ||
      DioExceptionType.sendTimeout ||
      DioExceptionType.connectionTimeout =>
        'timeout',
      DioExceptionType.cancel => 'cancelled',
      _ => 'error',
    });
  }

  void finish(String result) {
    if (!_clock.isRunning) return;
    _clock.stop();
    _record({
      'name': 'app.conversation.completed',
      'signal': 'event',
      'turn_id': id,
      'completed_ms': DateTime.now().millisecondsSinceEpoch,
      'duration_ms': _clock.elapsedMilliseconds,
      if (traceId != null) 'trace_id': traceId,
      'attributes': {'role': entry, 'result': result},
    });
  }
}

/// Keep terminal events across process restarts. Remove each item only after
/// the relay acknowledges its export. Retries send identical event data.
class ConversationLatency {
  ConversationLatency(this.url, this.token, {this.enabled = true, Dio? client})
      : _client = client ?? Dio();
  final String url;
  final bool enabled;
  final Future<String?> Function() token;
  final Dio _client;
  final _storage = const FlutterSecureStorage();
  final _random = Random.secure();
  final _pending = <String, Map<String, dynamic>>{};
  static const _prefix = 'conversation_latency_v1_';
  bool _busy = false, _disposed = false;
  Timer? _retry;

  ConversationTurn start(String entry) {
    final id = List.generate(
            16, (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0'))
        .join();
    return ConversationTurn(entry, id, (event) {
      if (enabled) unawaited(_save(id, event));
    });
  }

  Future<void> _save(String id, Map<String, dynamic> event) async {
    try {
      await _storage.write(key: '$_prefix$id', value: jsonEncode(event));
    } catch (_) {
      // Memory still covers storage outages while the app is running.
    }
    _pending[id] = event;
    await flush();
  }

  Future<void> restore() async {
    if (!enabled) return;
    try {
      for (final item in (await _storage.readAll()).entries) {
        if (item.key.startsWith(_prefix)) {
          _pending[item.key.substring(_prefix.length)] = jsonDecode(item.value);
        }
      }
    } catch (_) {}
    await flush();
  }

  Future<void> flush() async {
    if (_busy || _disposed || _pending.isEmpty) return;
    _busy = true;
    try {
      final access = await token();
      if (access == null) return;
      for (final item in _pending.entries.toList()) {
        if (_disposed) return;
        // Loki has bounded historical ingestion. An expired event must not
        // block newer turns when a device reconnects after a long absence.
        final age = DateTime.now().millisecondsSinceEpoch -
            (item.value['completed_ms'] as int);
        if (age > const Duration(days: 7).inMilliseconds) {
          await _storage.delete(key: '$_prefix${item.key}');
          _pending.remove(item.key);
          continue;
        }
        final response = await _client.post(url,
            data: {
              'events': [item.value]
            },
            options: Options(
                headers: {'Authorization': 'Bearer $access'},
                sendTimeout: const Duration(seconds: 10),
                receiveTimeout: const Duration(seconds: 15)));
        if (response.data?['accepted'] != 1) continue;
        await _storage.delete(key: '$_prefix${item.key}');
        _pending.remove(item.key);
      }
    } catch (_) {
      // Network and authentication failures are retried outside the chat path.
    } finally {
      _busy = false;
      _retry?.cancel();
      if (_pending.isNotEmpty && !_disposed) {
        _retry = Timer(const Duration(seconds: 30), flush);
      }
    }
  }

  void dispose() {
    _disposed = true;
    _retry?.cancel();
  }
}
