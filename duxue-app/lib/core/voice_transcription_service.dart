import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:record/record.dart';
import 'package:web_socket_channel/io.dart';

import 'token_storage.dart';

typedef TranscriptHandler = void Function(String text);
typedef VoiceErrorHandler = void Function(String message);

class VoiceTranscriptionService {
  VoiceTranscriptionService({
    required this.baseUrl,
    required this.tokens,
    AudioRecorder? recorder,
  }) : _recorder = recorder ?? AudioRecorder();

  final String baseUrl;
  final TokenStorage tokens;
  final AudioRecorder _recorder;
  IOWebSocketChannel? _socket;
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

  Future<void> start({
    required List<String> wardIds,
    required TranscriptHandler onPartial,
    required TranscriptHandler onFinal,
    required VoiceErrorHandler onError,
  }) async {
    final token = await tokens.access;
    if (token == null) throw StateError('登录已过期，请重新登录');
    if (!await _recorder.hasPermission()) {
      throw StateError('请允许麦克风权限后再试');
    }
    final socket = IOWebSocketChannel.connect(
      websocketUri(baseUrl),
      headers: {'Authorization': 'Bearer $token'},
    );
    _socket = socket;
    await socket.ready;
    _socketSubscription = socket.stream.listen((raw) {
      final event = jsonDecode(raw as String) as Map<String, dynamic>;
      switch (event['type']) {
        case 'partial':
          onPartial(event['text'] as String? ?? '');
        case 'final':
          onFinal(event['text'] as String? ?? '');
          unawaited(_closeSocket());
        case 'error':
          onError(event['message'] as String? ?? '语音识别暂不可用');
      }
    }, onError: (_, __) => onError('语音连接已断开'));
    socket.sink.add(jsonEncode({'type': 'start', 'ward_ids': wardIds}));
    final stream = await _recorder.startStream(const RecordConfig(
      encoder: AudioEncoder.pcm16bits,
      sampleRate: 16000,
      numChannels: 1,
    ));
    _audioSubscription = stream.listen(socket.sink.add, onError: (_, __) {
      onError('无法读取麦克风音频');
    });
  }

  Future<void> commit() async {
    await _audioSubscription?.cancel();
    _audioSubscription = null;
    await _recorder.stop();
    _socket?.sink.add(jsonEncode({'type': 'commit'}));
  }

  Future<void> cancel() async {
    await _audioSubscription?.cancel();
    _audioSubscription = null;
    await _recorder.cancel();
    _socket?.sink.add(jsonEncode({'type': 'cancel'}));
    await _closeSocket();
  }

  Future<void> dispose() async {
    await cancel();
    await _recorder.dispose();
  }

  Future<void> _closeSocket() async {
    await _socketSubscription?.cancel();
    _socketSubscription = null;
    await _socket?.sink.close();
    _socket = null;
  }
}
