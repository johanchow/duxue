import 'package:duxue_app/core/models.dart';
import 'package:duxue_app/features/login_page.dart';
import 'package:duxue_app/features/ward_pages.dart';
import 'package:duxue_app/providers.dart';
import 'package:duxue_app/shared/app_version_label.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

void main() {
  const commit = String.fromEnvironment('APP_COMMIT');
  const label = '版本 1.3.7 (Build 42)'
      '${commit == '' ? '' : ' · $commit'}';
  setUp(() {
    FlutterSecureStoragePlatform.instance =
        TestFlutterSecureStoragePlatform({});
    PackageInfo.setMockInitialValues(
      appName: '读学',
      packageName: 'com.duxue.app',
      version: '1.3.7',
      buildNumber: '42',
      buildSignature: '',
    );
  });

  testWidgets('login displays the installed package version and build',
      (tester) async {
    await tester.pumpWidget(const ProviderScope(
      child: MaterialApp(home: LoginPage()),
    ));
    await tester.pumpAndSettle();
    expect(find.text(label), findsOneWidget);
  });

  testWidgets(
      'guardian profile displays the installed package version and build',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [wardsProvider.overrideWith((ref) async => <Ward>[])],
      child: const MaterialApp(home: WardListPage()),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('我的'));
    await tester.pumpAndSettle();
    expect(find.text(label), findsOneWidget);
  });

  testWidgets('package lookup failure does not display an invented version',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [
        appPackageInfoProvider.overrideWith((ref) async {
          throw StateError('package unavailable');
        }),
      ],
      child: const MaterialApp(home: Scaffold(body: AppVersionLabel())),
    ));
    await tester.pumpAndSettle();
    expect(find.text('版本信息暂不可用'), findsOneWidget);
    expect(find.textContaining('Build'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
