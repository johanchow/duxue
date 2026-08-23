import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'features/login_page.dart';
import 'features/report_page.dart';
import 'features/ward_pages.dart';
import 'features/profile_pages.dart';
import 'features/day_story_pages.dart';
import 'providers.dart';
import 'shared/app_ui.dart';

void main() => runApp(const ProviderScope(child: DuxueApp()));

final routerProvider = Provider<GoRouter>((ref) {
  final authenticated = ref.watch(authProvider).valueOrNull ?? false;
  return GoRouter(
    initialLocation: authenticated ? '/wards' : '/login',
    redirect: (_, state) {
      if (!authenticated && state.matchedLocation != '/login') return '/login';
      if (authenticated && state.matchedLocation == '/login') return '/wards';
      return null;
    },
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
      GoRoute(path: '/ward-bind', builder: (_, __) => const WardBindPage()),
      GoRoute(
        path: '/wards',
        builder: (_, __) => const WardListPage(),
        routes: [
          GoRoute(
            path: ':id',
            builder: (_, state) =>
                WardDetailPage(wardId: state.pathParameters['id']!),
            routes: [
              GoRoute(
                path: 'report',
                builder: (_, state) =>
                    ReportPage(wardId: state.pathParameters['id']!),
              ),
              GoRoute(
                path: 'trend',
                builder: (_, state) =>
                    WeeklyTrendPage(wardId: state.pathParameters['id']!),
              ),
              GoRoute(
                path: 'profiles',
                builder: (_, state) =>
                    ProfileListPage(wardId: state.pathParameters['id']!),
              ),
              GoRoute(
                path: 'story',
                builder: (_, state) =>
                    GuardianStoryPage(wardId: state.pathParameters['id']!),
              ),
            ],
          ),
        ],
      ),
    ],
  );
});

class DuxueApp extends ConsumerWidget {
  const DuxueApp({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) => MaterialApp.router(
        title: '读学',
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: brandBlue),
          scaffoldBackgroundColor: appSurface,
          useMaterial3: true,
          appBarTheme: const AppBarTheme(
              backgroundColor: appSurface, elevation: 0, centerTitle: false),
          cardTheme: CardThemeData(
              color: Colors.white,
              elevation: 0,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                  side: const BorderSide(color: Color(0xffe2e8f0)))),
          inputDecorationTheme: InputDecorationTheme(
              filled: true,
              fillColor: Colors.white,
              border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: const BorderSide(color: Color(0xffe2e8f0)))),
        ),
        routerConfig: ref.watch(routerProvider),
      );
}
