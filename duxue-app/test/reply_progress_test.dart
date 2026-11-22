import 'package:duxue_app/shared/reply_progress.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _preview(List<ReplyStage> stages, {bool reduceMotion = false}) {
  return MaterialApp(
    home: MediaQuery(
      data: MediaQueryData(
        disableAnimations: reduceMotion,
        textScaler: const TextScaler.linear(1.5),
      ),
      child: Scaffold(
        body: Align(
          alignment: Alignment.topLeft,
          child: SizedBox(width: 320, child: ReplyProgress(stages: stages)),
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('a single real status takes up one line', (tester) async {
    await tester.pumpWidget(_preview([ReplyStage.preparing]));
    await tester.pump(const Duration(milliseconds: 250));
    await tester.pump(const Duration(milliseconds: 280));
    expect(tester.getSize(find.byType(ReplyProgress)).height, lessThan(60));
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('reply progress waits briefly and rolls actual stages upward',
      (tester) async {
    final stages = [ReplyStage.preparing];
    await tester.pumpWidget(_preview(stages));
    await tester.pump(const Duration(milliseconds: 249));
    final preparing = find.text(ReplyStage.preparing.label);
    expect(preparing, findsNothing);
    await tester.pump(const Duration(milliseconds: 1));
    await tester.pump(const Duration(milliseconds: 280));
    stages.add(ReplyStage.reading);
    await tester.pumpWidget(_preview(stages));
    final start = tester.getCenter(preparing);
    await tester.pump(const Duration(milliseconds: 140));
    final midway = tester.getCenter(preparing);
    await tester.pump(const Duration(milliseconds: 140));

    final reading = find.text(ReplyStage.reading.label);
    expect(midway.dy, lessThan(start.dy));
    expect(tester.getCenter(preparing).dy, lessThan(midway.dy));
    expect(tester.getCenter(reading).dy, greaterThan(midway.dy));
    expect(tester.getTopLeft(reading).dx, tester.getTopLeft(preparing).dx);
    expect(find.text(ReplyStage.solving.label), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('reduced motion shows only the current status', (tester) async {
    await tester.pumpWidget(_preview([
      ReplyStage.preparing,
      ReplyStage.reading,
      ReplyStage.solving,
    ], reduceMotion: true));
    await tester.pump(const Duration(milliseconds: 250));

    expect(find.text(ReplyStage.preparing.label), findsNothing);
    expect(find.text(ReplyStage.reading.label), findsNothing);
    expect(find.text(ReplyStage.solving.label), findsOneWidget);
    expect(find.byType(AnimatedPositioned), findsNothing);
  });
}
