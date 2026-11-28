import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/features/conversation_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _Pages extends ApiClient {
  _Pages() : super(baseUrl: 'http://localhost', tokens: const TokenStorage());
  final cursors = <String?>[];

  @override
  Future<ConversationPage> conversationPage({String? cursor}) async {
    cursors.add(cursor);
    return (
      items: [
        {'thread_id': 'a', 'title': '第一篇'},
        if (cursor == 'page2') {'thread_id': 'b', 'title': '第二篇'},
      ],
      next: cursor == null ? 'page2' : null,
    );
  }
}

void main() {
  testWidgets('历史对话加载后续页并保留已有条目', (tester) async {
    final api = _Pages();
    await tester.pumpWidget(MaterialApp(home: ConversationPicker(api: api)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('加载更多对话'));
    await tester.pumpAndSettle();
    expect(api.cursors, [null, 'page2']);
    expect(find.text('第一篇'), findsOneWidget);
    expect(find.text('第二篇'), findsOneWidget);
    expect(find.text('加载更多对话'), findsNothing);
  });
}
