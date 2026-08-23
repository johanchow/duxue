import 'package:duxue_app/shared/app_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('shared card preserves its content and tap action',
      (tester) async {
    var tapped = false;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppCard(
          onTap: () => tapped = true,
          child: const Text('今日报告等待生成'),
        ),
      ),
    ));

    expect(find.text('今日报告等待生成'), findsOneWidget);
    await tester.tap(find.text('今日报告等待生成'));
    expect(tapped, isTrue);
  });
}
