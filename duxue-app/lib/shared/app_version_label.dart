import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

final appPackageInfoProvider = FutureProvider<PackageInfo>(
  (ref) => PackageInfo.fromPlatform(),
);

/// Read the installed package so CI overrides and local builds stay accurate.
class AppVersionLabel extends ConsumerWidget {
  const AppVersionLabel({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    const commit = String.fromEnvironment('APP_COMMIT');
    return ref.watch(appPackageInfoProvider).when(
          data: (info) => SelectableText(
            '版本 ${info.version} (Build ${info.buildNumber})'
            '${commit.isEmpty ? '' : ' · $commit'}',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          loading: () => const SizedBox.shrink(),
          error: (error, stack) => Text(
            '版本信息暂不可用',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        );
  }
}
