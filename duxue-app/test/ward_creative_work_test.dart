import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/features/ward_creative_work.dart';
import 'package:duxue_app/providers.dart';
import 'package:duxue_app/shared/voice_composer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Api extends ApiClient {
  _Api() : super(baseUrl: 'http://localhost', tokens: const TokenStorage());
  String? title = '青蛙的船';
  String second = '故事第二页';
  bool saved = false;
  int revision = 1;
  Map<String, dynamic> doc() => {
        'artifact_id': 'w',
        'title': '青蛙的船',
        'saved': saved,
        'state_revision': revision,
        'can_undo': revision == 2,
        'can_redo': revision == 3,
        'pages': [
          for (final row in [('a', '故事第一页'), ('b', second)])
            {
              'block_id': row.$1,
              'text': row.$2,
              'illustration': {
                'kind': 'svg',
                'alt': '月亮',
                'svg':
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 360"><circle cx="100" cy="90" r="40" fill="gold"/></svg>'
              }
            }
        ]
      };
  @override
  Future<Map<String, dynamic>> creativeWork(String id) async => doc();
  @override
  Future<List<Map<String, dynamic>>> savedWorks() async => [
        if (title != null) {'artifact_id': 'w', 'title': title}
      ];
  @override
  Future<void> renameCreativeWork(String id, String name) async => title = name;
  @override
  Future<void> deleteCreativeWork(String id) async => title = null;
  @override
  Future<Map<String, dynamic>> changeCreativeWork(
      String id, Map<String, dynamic> cmd) async {
    expect(cmd['expected_revision'], revision++);
    switch (cmd['action']) {
      case 'revise':
        expect(cmd['block_id'], 'b');
        second = cmd['instruction'] as String;
      case 'undo':
        second = '故事第二页';
      case 'redo':
        second = '换成蓝帆';
      case 'save':
        saved = true;
    }
    return doc();
  }
}

void main() {
  testWidgets('作品改名后刷新列表，确认删除后显示空状态', (tester) async {
    final api = _Api();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardWorksLibrary())));
    await tester.pumpAndSettle();
    for (final action in ['重命名', '删除']) {
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text(action));
      await tester.pumpAndSettle();
      if (action == '重命名') {
        await tester.enterText(find.byType(TextFormField), '新标题');
        await tester.tap(find.text('保存'));
        await tester.pumpAndSettle();
        expect(find.text('新标题'), findsOneWidget);
      } else {
        await tester.tap(find.text('删除'));
        await tester.pumpAndSettle();
        expect(find.text('保存的作品会出现在这里'), findsOneWidget);
      }
    }
  });

  testWidgets('我的作品可重开，语音只修改选中页，撤销和重做恢复对应版本', (tester) async {
    await tester.binding.setSurfaceSize(const Size(480, 1100));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = _Api();
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: WardWorksLibrary())));
    await tester.pumpAndSettle();
    await tester.tap(find.text('青蛙的船'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('第 2 页'));
    await tester.pump();
    await tester
        .widget<VoiceComposer>(find.byType(VoiceComposer))
        .onVoiceFinal('换成蓝帆');
    await tester.pumpAndSettle();
    expect(find.text('换成蓝帆'), findsOneWidget);
    await tester.tap(find.byTooltip('撤销'));
    await tester.pumpAndSettle();
    expect(find.text('故事第二页'), findsOneWidget);
    await tester.tap(find.byTooltip('重做'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存到我的作品'));
    await tester.pumpAndSettle();
    expect(find.text('已保存到我的作品'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.text('青蛙的船'));
    await tester.pumpAndSettle();
    expect(find.text('故事第一页'), findsOneWidget);
    await tester.tap(find.text('第 2 页'));
    await tester.pump();
    expect(find.text('换成蓝帆'), findsOneWidget);
  });
}
