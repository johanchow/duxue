import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenStorage {
  const TokenStorage();
  static const _storage = FlutterSecureStorage();
  Future<String?> get access => _storage.read(key: 'access_token');
  Future<String?> get refresh => _storage.read(key: 'refresh_token');
  Future<String?> get wardId => _storage.read(key: 'ward_id');
  Future<String?> get companionThreadId =>
      _storage.read(key: 'companion_thread_id');
  Future<int?> get companionThreadVersion async {
    final value = await _storage.read(key: 'companion_thread_version');
    return value == null ? null : int.tryParse(value);
  }

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
    await _storage.delete(key: 'companion_thread_id');
    await _storage.delete(key: 'companion_thread_version');
  }

  Future<void> saveCompanionThread(String threadId, int threadVersion) async {
    await _storage.write(key: 'companion_thread_id', value: threadId);
    await _storage.write(
        key: 'companion_thread_version', value: '$threadVersion');
  }

  Future<void> clear() => _storage.deleteAll();
}
