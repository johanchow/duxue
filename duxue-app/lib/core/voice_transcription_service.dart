import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:record/record.dart';
import 'package:web_socket_channel/io.dart';

import 'token_storage.dart';
import 'telemetry.dart';

typedef TranscriptHandler = void Function(String text);
typedef VoiceErrorHandler = void Function(String message);

String voiceProtocolErrorMessage(Object? code) {
  if (code == 'unauthorized') return '登录已过期，请重新登录';
  return '语音识别暂不可用，请稍后重试';
}

typedef VoiceTranscriptionFactory = VoiceTranscription Function({
  required String baseUrl,
  required TokenStorage tokens,
  required AppTelemetry telemetry,
});

abstract interface class VoiceTranscription {
  Future<void> start({
    TranscriptHandler? onDisplayText,
    required TranscriptHandler onPartial,
    required TranscriptHandler onFinal,
    required VoiceErrorHandler onError,
  });
  Future<void> commit();
  Future<void> cancel();
  Future<void> dispose();
}

class VoiceTranscriptionService implements VoiceTranscription {
  VoiceTranscriptionService({
    required this.baseUrl,
    required this.tokens,
    required this.telemetry,
    AudioRecorder? recorder,
  }) : _recorder = recorder ?? AudioRecorder();

  final String baseUrl;
  final TokenStorage tokens;
  final AppTelemetry telemetry;
  final AudioRecorder _recorder;
  IOWebSocketChannel? _socket;
  Stopwatch? _commitLatency;
  StreamSubscription<Uint8List>? _audioSubscription;
  StreamSubscription<dynamic>? _socketSubscription;

  static Uri websocketUri(String baseUrl) {
    final api = Uri.parse(baseUrl);
    final scheme = api.scheme == 'https' ? 'wss' : 'ws';
    final basePath = api.path.endsWith('/')
        ? api.path.substring(0, api.path.length - 1)
        : api.path;
    return api.replace(scheme: scheme, path: '$basePath/ws/asr/transcribe');
  }

  @override
  Future<void> start({
    TranscriptHandler? onDisplayText,
    required TranscriptHandler onPartial,
    required TranscriptHandler onFinal,
    required VoiceErrorHandler onError,
  }) async {
    _commitLatency = null;
    const route = '/ws/asr/transcribe';
    final span =
        telemetry.startSpan('app.asr.session', attributes: {'route': route});
    final token = await tokens.access;
    if (token == null) throw StateError('登录已过期，请重新登录');
    if (!await _recorder.hasPermission()) {
      throw StateError('请允许麦克风权限后再试');
    }
    final socket = IOWebSocketChannel.connect(
      websocketUri(baseUrl),
      headers: {
        'Authorization': 'Bearer $token',
        if (span.traceparent != null) 'traceparent': span.traceparent!,
      },
    );
    _socket = socket;
    try {
      await socket.ready;
    } catch (_) {
      span.finish(attributes: {'result': 'error', 'error_kind': 'connect'});
      telemetry.recordMetric('app.asr.session', 1, attributes: {
        'result': 'error',
        'error_kind': 'connect',
        'route': route
      });
      await _closeSocket();
      rethrow;
    }
    if (_socket != socket) return;
    var terminal = false;
    _socketSubscription = socket.stream.listen((raw) {
      if (terminal || _socket != socket) return;
      final event = jsonDecode(raw as String) as Map<String, dynamic>;
      switch (event['type']) {
        case 'partial':
          onPartial(event['text'] as String? ?? '');
        case 'final':
          terminal = true;
          span.finish(attributes: {'result': 'success'});
          telemetry.recordMetric('app.asr.session', 1,
              attributes: {'result': 'success', 'route': route});
          final latency = _commitLatency;
          if (latency != null) {
            telemetry.recordMetric('app.asr.final_latency', latency.elapsedMilliseconds.toDouble());
          }
          final display = event['display_text'];
          if (display is String) onDisplayText?.call(display);
          onFinal(event['text'] as String? ?? '');
          unawaited(_closeSocket());
        case 'error':
          terminal = true;
          final errorKind = event['code'] == 'unauthorized' ? 'auth' : 'server';
          span.finish(attributes: {'result': 'error', 'error_kind': errorKind});
          telemetry.recordMetric('app.asr.session', 1, attributes: {
            'result': 'error',
            'error_kind': errorKind,
            'route': route
          });
          onError(voiceProtocolErrorMessage(event['code']));
          unawaited(cancel());
      }
    }, onError: (_, __) {
      if (terminal) return;
      terminal = true;
      span.finish(attributes: {'result': 'error', 'error_kind': 'socket'});
      telemetry.recordMetric('app.asr.session', 1, attributes: {
        'result': 'error',
        'error_kind': 'socket',
        'route': route
      });
      onError('语音连接已断开');
      unawaited(cancel());
    }, onDone: () {
      if (terminal || _socket != socket) return;
      terminal = true;
      span.finish(attributes: {'result': 'error', 'error_kind': 'disconnect'});
      onError('语音连接已断开');
      unawaited(cancel());
    });
    socket.sink.add(jsonEncode({
      'type': 'start',
      if (onDisplayText != null) 'display_transcript': true
    }));
    final stream = await _recorder.startStream(const RecordConfig(
      encoder: AudioEncoder.pcm16bits,
      sampleRate: 16000,
      numChannels: 1,
    ));
    if (terminal || _socket != socket) {
      await _recorder.cancel();
      return;
    }
    _audioSubscription = stream.listen(socket.sink.add, onError: (_, __) {
      if (terminal) return;
      terminal = true;
      onError('无法读取麦克风音频');
      unawaited(cancel());
    });
  }

  @override
  Future<void> commit() async {
    _commitLatency = Stopwatch()..start();
    await _audioSubscription?.cancel();
    _audioSubscription = null;
    await _recorder.stop();
    _socket?.sink.add(jsonEncode({'type': 'commit'}));
  }

  @override
  Future<void> cancel() async {
    await _audioSubscription?.cancel();
    _audioSubscription = null;
    await _recorder.cancel();
    if (_socket?.closeCode == null) {
      _socket?.sink.add(jsonEncode({'type': 'cancel'}));
    }
    await _closeSocket();
  }

  @override
  Future<void> dispose() async {
    await cancel();
    await _recorder.dispose();
  }

  Future<void> _closeSocket() async {
    final subscription = _socketSubscription;
    final socket = _socket;
    _socketSubscription = null;
    _socket = null;
    await subscription?.cancel();
    await socket?.sink.close();
  }
}
