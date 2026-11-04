import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:duxue_app/features/sprint_card.dart';

void main() {
  testWidgets(
      'pause and end have matching surfaces and remain disabled when busy',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SprintCard(
      sprint: const {
        'topic': '数学',
        'status': 'paused',
        'remaining_seconds': 1200,
        'target_seconds': 1200
      },
      busy: true,
      onAction: (_) async {},
      onHide: () {},
      onElapsed: () {},
    ))));
    final buttons =
        tester.widgetList<FilledButton>(find.byType(FilledButton)).toList();
    expect(buttons, hasLength(2));
    expect(buttons[0].style, buttons[1].style);
    expect(buttons.every((button) => button.onPressed == null), isTrue);
    expect(tester.getSize(find.byType(FilledButton).first),
        tester.getSize(find.byType(FilledButton).last));
  });

  testWidgets('standard sprint card stays within a compact height budget',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: Center(
      child: SizedBox(
          width: 350,
          child: SprintCard(
            sprint: const {
              'topic': '数学',
              'status': 'paused',
              'remaining_seconds': 1200,
              'target_seconds': 1200
            },
            onAction: (_) async {},
            onHide: () {},
            onElapsed: () {},
          )),
    ))));
    expect(tester.getSize(find.byKey(const Key('active-sprint-card'))).height,
        lessThanOrEqualTo(150));
  });

  testWidgets(
      'remaining bar drains, freezes on pause and resumes from server time',
      (tester) async {
    Future<void> show(String status, int remaining) =>
        tester.pumpWidget(MaterialApp(
            home: Scaffold(
                body: SprintCard(
          sprint: {
            'topic': '阅读',
            'status': status,
            'remaining_seconds': remaining,
            'target_seconds': 120
          },
          onAction: (_) async {},
          onHide: () {},
          onElapsed: () {},
        ))));
    double? fraction() => tester
        .widget<LinearProgressIndicator>(
            find.byKey(const Key('sprint-remaining-progress')))
        .value;
    await show('active', 90);
    expect(fraction(), .75);
    expect(find.text('1:30'), findsOneWidget);
    await tester.pump(const Duration(seconds: 30));
    expect(fraction(), .5);
    expect(find.text('1:00'), findsOneWidget);
    await show('paused', 60);
    await tester.pump(const Duration(minutes: 2));
    expect(fraction(), .5);
    await show('active', 60);
    await tester.pump(const Duration(seconds: 30));
    expect(fraction(), .25);
    expect(find.text('0:30'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('missing target never invents remaining progress',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SprintCard(
      sprint: const {
        'topic': '阅读',
        'status': 'paused',
        'remaining_seconds': 60
      },
      onAction: (_) async {},
      onHide: () {},
      onElapsed: () {},
    ))));
    expect(find.text('1:00'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNothing);
  });

  for (final brightness in Brightness.values) {
    testWidgets(
        'narrow card supports large text and icon actions in $brightness',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 720));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final actions = <String>[];
      var hidden = false;
      await tester.pumpWidget(MaterialApp(
        theme: ThemeData(brightness: brightness),
        home: MediaQuery(
          data: const MediaQueryData(textScaler: TextScaler.linear(1.6)),
          child: Scaffold(
              body: SingleChildScrollView(
                  padding: const EdgeInsets.all(20),
                  child: SprintCard(
                    sprint: const {
                      'topic': '读完这一本很长的课外阅读书',
                      'status': 'paused',
                      'remaining_seconds': 10800,
                      'target_seconds': 10800
                    },
                    onAction: (action) async => actions.add(action),
                    onHide: () => hidden = true,
                    onElapsed: () {},
                  ))),
        ),
      ));
      expect(tester.takeException(), isNull);
      await tester.ensureVisible(find.text('继续本轮'));
      await tester.tap(find.text('继续本轮'));
      await tester.ensureVisible(find.text('结束本轮'));
      await tester.tap(find.text('结束本轮'));
      await tester.ensureVisible(find.byTooltip('收起挑战'));
      await tester.tap(find.byTooltip('收起挑战'));
      expect(actions, ['resume', 'end']);
      expect(hidden, isTrue);
      expect(tester.takeException(), isNull);
    });
  }

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
