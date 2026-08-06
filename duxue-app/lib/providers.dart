import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/api_client.dart';
import 'core/models.dart';
import 'core/token_storage.dart';

/// Compile with `--dart-define=API_BASE_URL=https://api.example.com`.
/// This is intentionally a build-time value: mobile clients cannot read the
/// server's `.env.prod` after they have been installed.
const apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);
final tokenStorageProvider = Provider((_) => const TokenStorage());
final apiProvider = Provider(
  (ref) =>
      ApiClient(baseUrl: apiBaseUrl, tokens: ref.watch(tokenStorageProvider)),
);
final authProvider = AsyncNotifierProvider<AuthController, bool>(
  AuthController.new,
);

class AuthController extends AsyncNotifier<bool> {
  @override
  Future<bool> build() async =>
      (await ref.read(tokenStorageProvider).access) != null;
  Future<void> login(String email, String password) async {
    state = const AsyncLoading();
    try {
      await ref.read(apiProvider).login(email, password);
      state = const AsyncData(true);
    } catch (_) {
      state = const AsyncData(false);
      rethrow;
    }
  }

  Future<void> register(String name, String email, String password) async {
    state = const AsyncLoading();
    try {
      await ref.read(apiProvider).register(name, email, password);
      state = const AsyncData(true);
    } catch (_) {
      state = const AsyncData(false);
      rethrow;
    }
  }

  Future<void> logout() async {
    await ref.read(tokenStorageProvider).clear();
    state = const AsyncData(false);
  }
}

final wardsProvider = FutureProvider<List<Ward>>(
  (ref) => ref.watch(apiProvider).wards(),
);
final devicesProvider = StreamProvider.family<List<Device>, String>((
  ref,
  wardId,
) async* {
  while (true) {
    yield await ref.read(apiProvider).devices(wardId);
    await Future<void>.delayed(const Duration(seconds: 30));
  }
});
final reportProvider =
    FutureProvider.family<DailyReport, ({String wardId, DateTime date})>(
  (ref, key) => ref.watch(apiProvider).report(key.wardId, key.date),
);
final weeklyTrendProvider =
    FutureProvider.family<WeeklyTrend, ({String wardId, DateTime endDate})>(
  (ref, key) => ref.watch(apiProvider).weeklyTrend(key.wardId, key.endDate),
);
final profilesProvider = FutureProvider<List<AnalysisProfile>>(
  (ref) => ref.watch(apiProvider).profiles(),
);
final profileProvider = FutureProvider.family<AnalysisProfile, String>(
  (ref, id) => ref.watch(apiProvider).profile(id),
);
