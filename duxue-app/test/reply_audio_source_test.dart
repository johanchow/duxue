import 'dart:async';
import 'dart:io';

import 'package:duxue_app/core/speech_playback.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('native source streams before completion and handles byte-range retries',
      () async {
    final input = StreamController<List<int>>();
    final source = await ReplyAudioSource.open(input.stream);
    final client = HttpClient();
    addTearDown(() async {
      client.close(force: true);
      await source.close();
    });
    final request = await client.getUrl(source.uri);
    final response = request.close();
    input.add([1, 2]);
    final first = await response;
    expect(first.headers.chunkedTransferEncoding, isTrue);
    final reader = StreamIterator(first);
    expect(await reader.moveNext(), isTrue);
    expect(reader.current, [1, 2]);
    input.add([3, 4]);
    await input.close();
    expect(await reader.moveNext(), isTrue);
    expect(await reader.moveNext(), isFalse);
    final retry = await client.getUrl(source.uri);
    retry.headers.set('Range', 'bytes=1-2');
    final range = await retry.close();
    expect(range.statusCode, 206);
    expect(await range.expand((part) => part).toList(), [2, 3]);
  });
}
