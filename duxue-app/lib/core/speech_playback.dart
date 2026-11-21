import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:just_audio/just_audio.dart' as progressive;

/// 播放已合成的 MP3，或在服务端失败时用设备朗读原文。
abstract class SpeechPlayback {
  Stream<void> get onComplete;
  Future<void> playMp3(Uint8List bytes);
  Future<void> playStream(Stream<List<int>> frames);
  Future<void> speak(String text, String locale);
  Future<void> stop();
  Future<void> dispose();
}

class DeviceSpeechPlayback implements SpeechPlayback {
  final AudioPlayer _player = AudioPlayer();
  progressive.AudioPlayer? _streamPlayer;
  ReplyAudioSource? _source;
  final _completed = StreamController<void>.broadcast();
  late final StreamSubscription<void> _mp3Complete;
  DeviceSpeechPlayback() {
    _mp3Complete = _player.onPlayerComplete.listen(_completed.add);
  }
  FlutterTts? _tts;
  int _generation = 0;

  @override
  Stream<void> get onComplete => _completed.stream;

  @override
  Future<void> playStream(Stream<List<int>> frames) async {
    final generation = ++_generation;
    final player = _streamPlayer ??= progressive.AudioPlayer(
      audioLoadConfiguration: const progressive.AudioLoadConfiguration(
        androidLoadControl: progressive.AndroidLoadControl(
          bufferForPlaybackDuration: Duration(milliseconds: 200),
        ),
      ),
    );
    await _source?.close();
    final source = _source = await ReplyAudioSource.open(frames);
    if (generation != _generation) {
      await source.close();
      return;
    }
    await player.setUrl(source.uri.toString());
    if (generation != _generation) return;
    unawaited(player.play().then((_) {
      if (generation == _generation && !_completed.isClosed) {
        _completed.add(null);
      }
    }, onError: (Object error, StackTrace stack) {
      if (generation == _generation && !_completed.isClosed) {
        _completed.addError(error, stack);
      }
    }));
  }

  @override
  Future<void> playMp3(Uint8List bytes) async {
    final generation = ++_generation;
    await _streamPlayer?.stop();
    await _tts?.stop();
    if (generation != _generation) return;
    await _player.stop();
    if (generation != _generation) return;
    await _player.play(BytesSource(bytes));
  }

  @override
  Future<void> speak(String text, String locale) async {
    final generation = ++_generation;
    await _streamPlayer?.stop();
    await _player.stop();
    if (generation != _generation) return;
    final tts = _tts ??= FlutterTts();
    await tts.stop();
    await tts.setLanguage(locale);
    if (generation != _generation) return;
    await tts.speak(text);
  }

  @override
  Future<void> stop() async {
    _generation++;
    await _source?.close();
    _source = null;
    await _streamPlayer?.stop();
    await _player.stop();
    await _tts?.stop();
  }

  @override
  Future<void> dispose() async {
    await stop();
    await _mp3Complete.cancel();
    await _streamPlayer?.dispose();
    await _player.dispose();
    await _completed.close();
  }
}

/// A private, per-playback HTTP response for the native decoder. Explicit chunk
/// termination lets Media3 distinguish the end of a reply from a lost live feed.
class ReplyAudioSource {
  final HttpServer _server;
  final Uri uri;

  static Future<ReplyAudioSource> open(Stream<List<int>> frames) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final random = Random.secure();
    final path = List.generate(
            16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0'))
        .join();
    return ReplyAudioSource._(
        server, Uri.http('127.0.0.1:${server.port}', '/$path.mp3'), frames);
  }

  ReplyAudioSource._(this._server, this.uri, Stream<List<int>> frames) {
    _server.listen(_serve);
    _sub = frames.listen((frame) {
      _chunks.add(frame);
      _length += frame.length;
      _signal();
    }, onError: (Object error) {
      _error = error;
      _finish();
    }, onDone: _finish, cancelOnError: true);
  }

  final _chunks = <List<int>>[];
  late final StreamSubscription<List<int>> _sub;
  final _done = Completer<void>();
  var _changed = Completer<void>();
  int _length = 0;
  Object? _error;

  void _signal() {
    _changed.complete();
    _changed = Completer<void>();
  }

  void _finish() {
    if (_done.isCompleted) return;
    _done.complete();
    _signal();
  }

  Future<void> close() async {
    _finish();
    _chunks.clear();
    _length = 0;
    await _server.close(force: true);
    await _sub.cancel();
  }

  Stream<List<int>> _read(int start, int? end) async* {
    var index = 0;
    var offset = 0;
    while (end == null || offset < end) {
      if (index == _chunks.length) {
        if (_error != null) throw _error!;
        if (_done.isCompleted) return;
        await _changed.future;
        continue;
      }
      if (index > _chunks.length) return; // The player released this source.
      final chunk = _chunks[index++];
      final next = offset + chunk.length;
      if (next > start) {
        final from = (start - offset).clamp(0, chunk.length);
        final to =
            end == null ? chunk.length : (end - offset).clamp(0, chunk.length);
        yield from == 0 && to == chunk.length ? chunk : chunk.sublist(from, to);
      }
      offset = next;
    }
  }

  Future<void> _serve(HttpRequest request) async {
    final response = request.response;
    try {
      if (request.method != 'GET' || request.uri.path != uri.path) {
        response.statusCode = HttpStatus.notFound;
        return;
      }
      response.headers.contentType = ContentType('audio', 'mpeg');
      response.bufferOutput = false;
      final range = RegExp(r'^bytes=(\d+)-(\d*)$')
          .firstMatch(request.headers.value(HttpHeaders.rangeHeader) ?? '');
      if (range != null && _done.isCompleted) {
        final start = int.tryParse(range[1]!);
        final last = int.tryParse(range[2]!) ?? _length - 1;
        if (start == null || start >= _length || last < start) {
          response.statusCode = HttpStatus.requestedRangeNotSatisfiable;
          response.headers
              .set(HttpHeaders.contentRangeHeader, 'bytes */$_length');
          return;
        }
        final end = min(last, _length - 1) + 1;
        response.statusCode = HttpStatus.partialContent;
        response.headers.set(
            HttpHeaders.contentRangeHeader, 'bytes $start-${end - 1}/$_length');
        response.contentLength = end - start;
        await response.addStream(_read(start, end));
      } else {
        if (_done.isCompleted) {
          response.contentLength = _length;
        } else {
          response.headers.chunkedTransferEncoding = true;
        }
        await response.addStream(_read(0, null));
      }
    } catch (_) {
      // End a failed or cancelled synthesis as a broken response, never a cached MP3.
      try {
        (await response.detachSocket(writeHeaders: false)).destroy();
      } catch (_) {}
    } finally {
      try {
        await response.close();
      } on IOException {
        // The native player may stop before the final frame.
      }
    }
  }
}
