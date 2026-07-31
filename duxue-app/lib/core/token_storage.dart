import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenStorage {
  const TokenStorage();
  static const _storage = FlutterSecureStorage();
  Future<String?> get access => _storage.read(key: 'access_token');
  Future<String?> get refresh => _storage.read(key: 'refresh_token');
  Future<void> save(String access, String? refresh) async {
    await _storage.write(key: 'access_token', value: access);
    if (refresh != null) await _storage.write(key: 'refresh_token', value: refresh);
  }
  Future<void> clear() => _storage.deleteAll();
}
