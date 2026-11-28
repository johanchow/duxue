import 'package:duxue_app/features/guardian_courseware/math_stage_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('description-only geometry cannot render the fixed triangle',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: MathStageView(visualSpec: {
          'kind': 'component_scene',
          'static_fallback_text': '46拆成40和6，39拆成30和9。',
          'payload': {
            'component': 'geometry_2d',
            'description': '用两个长方形表示整十和个位',
          },
        }),
      ),
    ));
    expect(find.text('46拆成40和6，39拆成30和9。'), findsOneWidget);
    expect(find.text('重置'), findsNothing);
  });

  testWidgets('unsupported shapes show their explanation instead of a triangle',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: MathStageView(visualSpec: {
          'kind': 'component_scene',
          'title': '满十进一',
          'static_fallback_text': '6+9=15，个位写5，向十位进1。',
          'payload': {
            'component': 'geometry_2d',
            'shapes': [
              {'type': 'text', 'x': 50, 'y': 50, 'text': '6+9=15'},
            ],
          },
        }),
      ),
    ));
    expect(find.byKey(const ValueKey('math-stage-static-fallback')),
        findsOneWidget);
    expect(find.text('6+9=15，个位写5，向十位进1。'), findsOneWidget);
    expect(find.text('重置'), findsNothing);
    expect(find.text('交互数理图示'), findsNothing);
  });

  testWidgets('switching from a preset to custom shapes rechecks compatibility',
      (tester) async {
    Future<void> show(Map<String, dynamic> spec) => tester.pumpWidget(
          MaterialApp(home: Scaffold(body: MathStageView(visualSpec: spec))),
        );
    const preset = {
      'kind': 'component_scene',
      'payload': {'component': 'solid_geometry_3d', 'shape': 'cube'},
    };
    await show(preset);
    expect(find.text('重置'), findsOneWidget);

    await show({
      'kind': 'component_scene',
      'alt': '整十与个位的拆分说明',
      'payload': {'component': 'geometry_2d', 'shapes': []},
    });
    expect(find.text('整十与个位的拆分说明'), findsOneWidget);
    expect(find.text('重置'), findsNothing);

    await show(preset);
    expect(
        find.byKey(const ValueKey('math-stage-static-fallback')), findsNothing);
    expect(find.text('重置'), findsOneWidget);
  });
}
