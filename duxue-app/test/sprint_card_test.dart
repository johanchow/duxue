import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:duxue_app/features/sprint_card.dart';

void main() {
  testWidgets(
      'deadline hides a round without completing a task or awarding focus',
      (tester) async {
    var elapsed = 0;
    final actions = <String>[];
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SprintCard(
                sprint: const {
          'id': 'one',
          'topic': '阅读',
          'status': 'active',
          'remaining_seconds': 2
        },
                onAction: (action) async {
                  actions.add(action);
                },
                onHide: () {},
                onElapsed: () {
                  elapsed++;
                }))));
    await tester.pump(const Duration(seconds: 3));
    expect(elapsed, 1);
    expect(actions, isEmpty);
    expect(find.byKey(const Key('active-sprint-card')), findsNothing);
    expect(find.textContaining('成功专注'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });
  testWidgets('a paused sprint does not consume target time', (tester) async {
    var elapsed = 0;
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SprintCard(
                sprint: const {
          'topic': '阅读',
          'status': 'paused',
          'remaining_seconds': 60
        },
                onAction: (action) async {},
                onHide: () {},
                onElapsed: () {
                  elapsed++;
                }))));
    await tester.pump(const Duration(minutes: 5));
    expect(elapsed, 0);
    expect(find.text('本轮已暂停'), findsOneWidget);
  });
}
