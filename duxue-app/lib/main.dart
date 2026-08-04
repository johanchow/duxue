import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'core/models.dart';
import 'features/login_page.dart';
import 'features/report_page.dart';
import 'features/ward_pages.dart';
import 'providers.dart';

void main() => runApp(const ProviderScope(child: DuxueApp()));

final routerProvider = Provider<GoRouter>((ref) {
  final authenticated = ref.watch(authProvider).valueOrNull ?? false;
  return GoRouter(initialLocation: authenticated ? '/wards' : '/login', redirect: (_, state) {
    if (!authenticated && state.matchedLocation != '/login') return '/login';
    if (authenticated && state.matchedLocation == '/login') return '/wards';
    return null;
  }, routes: [
    GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
    GoRoute(path: '/wards', builder: (_, __) => const WardListPage(), routes: [
      GoRoute(path: ':id', builder: (_, state) => WardDetailPage(ward: state.extra! as Ward), routes: [
        GoRoute(path: 'report', builder: (_, state) => ReportPage(ward: state.extra! as Ward)),
      ]),
    ]),
  ]);
});

class DuxueApp extends ConsumerWidget {
  const DuxueApp({super.key});
  @override Widget build(BuildContext context, WidgetRef ref) => MaterialApp.router(
    title: '读学', theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff2563eb)), useMaterial3: true),
    routerConfig: ref.watch(routerProvider),
  );
}
