import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenStorage {
  const TokenStorage();
  static const _storage = FlutterSecureStorage();
  Future<String?> get access => _storage.read(key: 'access_token');
  Future<String?> get refresh => _storage.read(key: 'refresh_token');
  Future<String?> get wardId => _storage.read(key: 'ward_id');
  Future<void> save(String access, String? refresh) async {
    await _storage.write(key: 'access_token', value: access);
    await _storage.delete(key: 'ward_id');
    if (refresh != null) {
      await _storage.write(key: 'refresh_token', value: refresh);
    } else {
      await _storage.delete(key: 'refresh_token');
    }
  }

  Future<void> saveWard(String access, String refresh, String wardId) async {
    await _storage.write(key: 'access_token', value: access);
    await _storage.write(key: 'refresh_token', value: refresh);
    await _storage.write(key: 'ward_id', value: wardId);
  }

  Future<void> clear() => _storage.deleteAll();
}
