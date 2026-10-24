import 'dart:convert';
import 'dart:io';

import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:flutter_test/flutter_test.dart';

class _MemoryTokens extends TokenStorage {
  _MemoryTokens(
      {required this.accessToken,
      required this.refreshToken,
      required this.ward});

  String? accessToken;
  String? refreshToken;
  String? ward;
  var cleared = false;

  @override
  Future<String?> get access async => accessToken;

  @override
  Future<String?> get refresh async => refreshToken;

  @override
  Future<String?> get wardId async => ward;

  @override
  Future<void> saveWard(String access, String refresh, String wardId) async {
    accessToken = access;
    refreshToken = refresh;
    ward = wardId;
  }

  @override
  Future<void> save(String access, String? refresh) async {
    accessToken = access;
    refreshToken = refresh;
    ward = null;
  }

  @override
  Future<void> clear() async {
    cleared = true;
    accessToken = null;
    refreshToken = null;
    ward = null;
  }
}

void main() {
  test('guardian email code, registration and login use code without password',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(server.close);
    final calls = <(String, Map<String, dynamic>)>[];
    server.listen((request) async {
      final payload = jsonDecode(await utf8.decoder.bind(request).join())
          as Map<String, dynamic>;
      calls.add((request.uri.path, payload));
      request.response.headers.contentType = ContentType.json;
      if (request.uri.path == '/auth/email-code/send') {
        request.response.statusCode = HttpStatus.accepted;
        request.response.write('{}');
      } else {
        request.response.write(jsonEncode({
          'access_token': 'guardian-access',
          'refresh_token': 'guardian-refresh',
          'token_type': 'bearer',
        }));
      }
      await request.response.close();
    });
    final tokens =
        _MemoryTokens(accessToken: null, refreshToken: null, ward: null);
    final api = ApiClient(
      baseUrl: 'http://${server.address.address}:${server.port}',
      tokens: tokens,
    );

    await api.sendEmailCode('parent@example.com');
    await api.register('Parent', 'parent@example.com', '123456');
    await api.login('parent@example.com', '654321');

    expect(calls.map((call) => call.$1).toList(),
        ['/auth/email-code/send', '/auth/register', '/auth/login']);
    expect(calls[0].$2, {'email': 'parent@example.com'});
    expect(calls[1].$2,
        {'name': 'Parent', 'email': 'parent@example.com', 'code': '123456'});
    expect(calls[2].$2, {'email': 'parent@example.com', 'code': '654321'});
    expect(tokens.accessToken, 'guardian-access');
    expect(tokens.refreshToken, 'guardian-refresh');
  });

  test('a role-rejected retry does not clear a successfully refreshed session',
      () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(server.close);
    final tokens = _MemoryTokens(
      accessToken: 'old-access',
      refreshToken: 'ward-refresh',
      ward: 'ward-1',
    );
    var refreshCalls = 0;
    server.listen((request) async {
      request.response.headers.contentType = ContentType.json;
      if (request.uri.path == '/ward-auth/refresh') {
        refreshCalls++;
        request.response.statusCode = HttpStatus.ok;
        request.response.write(jsonEncode({
          'access_token': 'new-access',
          'refresh_token': 'new-refresh',
          'token_type': 'bearer',
        }));
      } else {
        // This endpoint is guardian-only.  The renewed Ward token is valid,
        // but is still not authorized to call it.
        expect(request.headers.value(HttpHeaders.authorizationHeader),
            anyOf('Bearer old-access', 'Bearer new-access'));
        request.response.statusCode = HttpStatus.unauthorized;
        request.response.write('{}');
      }
      await request.response.close();
    });

    final client = ApiClient(
      baseUrl: 'http://${server.address.address}:${server.port}',
      tokens: tokens,
    );

    await expectLater(client.devices('ward-1'), throwsA(isA<Object>()));

    expect(refreshCalls, 1);
    expect(tokens.cleared, isFalse);
    expect(tokens.accessToken, 'new-access');
    expect(tokens.refreshToken, 'new-refresh');
    expect(tokens.ward, 'ward-1');
  });
}
