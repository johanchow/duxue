import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('release uses pubspec version and CI build number in APK and filename',
      () async {
    final workflow =
        File('../.github/workflows/app-release.yml').readAsLinesSync();
    final start = workflow.indexWhere(
        (line) => line.trim() == '- name: Build signed release APK');
    final run = workflow.indexWhere((line) => line.trim() == 'run: |', start);
    final script = workflow
        .skip(run + 1)
        .takeWhile((line) => line.startsWith('          ') || line.isEmpty)
        .map((line) => line.isEmpty ? line : line.substring(10))
        .join('\n');

    for (final version in ['0.2.0', '1.3.7']) {
      final root = Directory.systemTemp.createTempSync('guardian-version-');
      addTearDown(() => root.deleteSync(recursive: true));
      File('${root.path}/pubspec.yaml')
          .writeAsStringSync('version: $version+999\n');
      final bin = Directory('${root.path}/bin')..createSync();
      Directory('${root.path}/output').createSync();
      final flutter = File('${bin.path}/flutter')
        ..writeAsStringSync('''#!/bin/bash
set -eu
if [ "\$1" = pub ]; then exit 0; fi
version="\$(awk '/^version:/ {print \$2}' pubspec.yaml)"
version="\${version%%+*}"
build=999
for arg in "\$@"; do
  case "\$arg" in
    --build-name=*) version="\${arg#*=}" ;;
    --build-number=*) build="\${arg#*=}" ;;
  esac
done
mkdir -p build/app/outputs/flutter-apk
printf '%s+%s' "\$version" "\$build" > build/app/outputs/flutter-apk/app-release.apk
printf '%s\\n' "\$@" > args.txt
''');
      Process.runSync('chmod', ['+x', flutter.path]);
      final result = await Process.run('bash', ['-eu', '-c', script],
          workingDirectory: root.path,
          environment: {
            'PATH': '${bin.path}:${Platform.environment['PATH']}',
            'API_BASE_URL': 'https://example.test/api',
            'RUNNER_TEMP': '${root.path}/output',
            'GITHUB_RUN_NUMBER': '42',
            'GITHUB_SHA': 'abcdef1234567890',
            'GITHUB_OUTPUT': '${root.path}/step-output',
          });
      expect(result.exitCode, 0, reason: '${result.stderr}');
      final apks =
          Directory('${root.path}/output').listSync().whereType<File>();
      expect(apks.single.readAsStringSync(), '$version+42');
      expect(apks.single.uri.pathSegments.last,
          'guardian-$version+42-abcdef1.apk');
      expect(
          LineSplitter.split(File('${root.path}/args.txt').readAsStringSync()),
          contains('--dart-define=APP_COMMIT=abcdef1'));
      expect(File('${root.path}/step-output').readAsStringSync(),
          'artifact_name=guardian-$version+42-abcdef1\n');
      expect(File('${root.path}/pubspec.yaml').readAsStringSync(),
          'version: $version+999\n');
    }
  });
}
