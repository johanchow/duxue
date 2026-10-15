import 'package:duxue_app/features/visual_block.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const steps = {
  'kind': 'steps',
  'alt': '水循环分三步',
  'title': '水循环',
  'steps': [
    {'label': '蒸发'},
    {'label': '凝结', 'detail': '水汽变成小水珠'},
    {'label': '降水'},
  ],
};
const compare = {
  'kind': 'compare',
  'alt': '植物细胞和动物细胞的区别',
  'columns': [
    {'title': '植物细胞', 'items': ['有细胞壁', '有叶绿体']},
    {'title': '动物细胞', 'items': ['没有细胞壁', '没有叶绿体']},
  ],
  'row_labels': ['外层', '能量'],
};
const segment = {
  'kind': 'segment',
  'alt': '小明 3 份，小红 5 份，合计未知',
  'bars': [
    {
      'label': '小明',
      'segments': [
        {'value': 3}
      ]
    },
    {
      'label': '小红',
      'segments': [
        {'value': 5},
        {'unknown': true, 'label': '多'}
      ]
    },
  ],
  'brackets': [
    {'bar': 1, 'label': '合计', 'unknown': true}
  ],
};
const numberLine = {
  'kind': 'number_line',
  'alt': '数轴上标出 -2 和区间',
  'min': -5,
  'max': 5,
  'step': 1,
  'marks': [
    {'label': 'A', 'at': -2},
    {'label': '区间', 'start': 0, 'end': 3, 'end_closed': false},
    {'label': 'x', 'unknown': true},
  ],
};
const svgVisual = {
  'kind': 'svg',
  'alt': '直角三角形两直角边为 3 和 4，斜边未知',
  'title': '直角三角形',
  'svg': '<svg viewBox="0 0 680 180" width="100%" role="img">'
      '<polygon points="220,140 220,40 380,140" fill="#E6F1FB" stroke="#185FA5" stroke-width="1.5"/>'
      '<text x="200" y="95" font-size="13" fill="var(--color-text-primary)">3</text>'
      '<text x="300" y="160" font-size="13" fill="#0C447C">4</text>'
      '<text x="315" y="82" font-size="13" fill="#A32D2D">?</text>'
      '</svg>',
};

Future<void> pump(WidgetTester tester, Map<String, dynamic> visual,
    {Size size = const Size(360, 640),
    Brightness brightness = Brightness.light,
    double textScale = 1.0}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    theme: ThemeData(brightness: brightness, useMaterial3: true),
    builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!),
    home: Scaffold(body: SingleChildScrollView(child: VisualBlock(visual: visual))),
  ));
}

void main() {
  testWidgets('steps shows numbered steps in order', (tester) async {
    await pump(tester, steps);
    expect(find.byKey(const ValueKey('visual-block')), findsOneWidget);
    expect(find.text('水循环'), findsOneWidget);
    for (final text in ['蒸发', '凝结', '水汽变成小水珠', '降水', '1', '2', '3']) {
      expect(find.text(text), findsOneWidget);
    }
    expect(tester.takeException(), isNull);
  });

  testWidgets('compare shows header cells and aligned rows', (tester) async {
    await pump(tester, compare);
    for (final text in ['植物细胞', '动物细胞', '外层', '能量', '有叶绿体', '没有叶绿体']) {
      expect(find.text(text), findsOneWidget);
    }
  });

  testWidgets('segment draws known and unknown parts and a bracket', (tester) async {
    await pump(tester, segment);
    expect(find.text('小明'), findsOneWidget);
    expect(find.text('3'), findsOneWidget);
    expect(find.byKey(const ValueKey('segment-unknown')), findsOneWidget);
    expect(find.text('合计?'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('number line paints and lists unknown marks beside the axis', (tester) async {
    await pump(tester, numberLine);
    expect(find.byKey(const ValueKey('number-line-paint')), findsOneWidget);
    expect(find.byKey(const ValueKey('number-line-unknown')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('svg renders with flutter_svg and materializes theme tokens', (tester) async {
    await pump(tester, svgVisual);
    expect(find.byKey(const ValueKey('visual-block')), findsOneWidget);
    expect(find.byKey(const ValueKey('svg-visual-view')), findsOneWidget);
    expect(find.text('直角三角形'), findsOneWidget);
    expect(tester.takeException(), isNull);

    final light = materializeSvgTheme(svgVisual['svg'] as String, Brightness.light);
    expect(light, contains('#1A1A18'));
    expect(light, contains('#E6F1FB'));

    final dark = materializeSvgTheme(svgVisual['svg'] as String, Brightness.dark);
    expect(dark, contains('#F2F1ED'));
    expect(dark, contains('#0C447C'));
    expect(dark, contains('#B5D4F4'));

    final commentedSvg = {
      ...svgVisual,
      'svg': '<!-- Background -->${svgVisual['svg']}',
    };
    expect(VisualData.tryParse(commentedSvg), isNotNull);
    expect(
      VisualData.tryParse({
        ...compare,
        'columns': [
          {'title': '反射 (Reflection)', 'items': ['光碰到物体表面弹回', '入射角等于反射角']},
          {'title': '折射 (Refraction)', 'items': ['光进入另一种介质发生偏折', '传播速度改变导致方向变化']},
        ],
      }),
      isNotNull,
    );
  });

  for (final entry in {
    'steps': steps,
    'compare': compare,
    'segment': segment,
    'number_line': numberLine,
    'svg': svgVisual,
  }.entries) {
    testWidgets('${entry.key} works on a narrow screen in dark mode with large text',
        (tester) async {
      await pump(tester, entry.value,
          size: const Size(280, 600), brightness: Brightness.dark, textScale: 1.6);
      expect(find.byKey(const ValueKey('visual-block')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('${entry.key} exposes alt text to screen readers', (tester) async {
      final handle = tester.ensureSemantics();
      await pump(tester, entry.value);
      expect(find.bySemanticsLabel(RegExp(entry.value['alt'] as String)), findsOneWidget);
      handle.dispose();
    });
  }

  testWidgets('steps announce each step in order', (tester) async {
    final handle = tester.ensureSemantics();
    await pump(tester, steps);
    expect(find.bySemanticsLabel(RegExp('第1步，蒸发。第2步，凝结，水汽变成小水珠。第3步，降水')),
        findsOneWidget);
    handle.dispose();
  });

  group('unusable visuals are not drawn and never throw', () {
    final bad = <String, Map<String, dynamic>>{
      'unknown kind': {'kind': 'geometry', 'alt': '三角形'},
      'no alt': {...steps, 'alt': ''},
      'one step': {...steps, 'steps': [{'label': '只有一步'}]},
      'six steps': {...steps, 'steps': [for (var i = 0; i < 6; i++) {'label': '步$i'}]},
      'steps not a list': {...steps, 'steps': 'x'},
      'too-long label': {...steps, 'steps': [{'label': 'x' * 121}, {'label': 'y'}]},
      'misaligned compare': {
        ...compare,
        'columns': [
          {'title': 'a', 'items': ['1']},
          {'title': 'b', 'items': ['1', '2']}
        ]
      },
      'unknown carries a value': {
        ...segment,
        'bars': [
          {
            'label': 'a',
            'segments': [
              {'unknown': true, 'value': 7}
            ]
          }
        ],
        'brackets': []
      },
      'bracket on a missing bar': {
        ...segment,
        'brackets': [
          {'bar': 9, 'label': 'x'}
        ]
      },
      'number line too dense': {...numberLine, 'step': 0.1},
      'mark outside range': {
        ...numberLine,
        'marks': [
          {'at': 99}
        ]
      },
      'unknown mark with a position': {
        ...numberLine,
        'marks': [
          {'unknown': true, 'at': 2}
        ]
      },
      'svg with wrong viewBox width': {
        ...svgVisual,
        'svg': (svgVisual['svg'] as String).replaceAll('0 0 680 180', '0 0 500 180'),
      },
      'svg with script tag': {
        ...svgVisual,
        'svg': (svgVisual['svg'] as String).replaceAll('</svg>', '<script>x()</script></svg>'),
      },
      'svg with onclick handler': {
        ...svgVisual,
        'svg': (svgVisual['svg'] as String).replaceAll('<polygon ', '<polygon onclick="x()" '),
      },
      'svg without shapes': {
        ...svgVisual,
        'svg': '<svg viewBox="0 0 680 120"><title>空图</title></svg>',
      },
    };
    for (final entry in bad.entries) {
      testWidgets(entry.key, (tester) async {
        await pump(tester, entry.value);
        expect(find.byKey(const ValueKey('visual-block')), findsNothing);
        expect(tester.takeException(), isNull);
      });
    }
  });

  group('visualFromInteraction', () {
    test('returns the visual part of a text_visual interaction', () {
      final visual = visualFromInteraction({
        'kind': 'text_visual',
        'parts': [
          {'type': 'text', 'text': '你好'},
          {'type': 'visual', 'visual': steps},
        ],
      });
      expect(visual?['kind'], 'steps');
    });

    test('ignores other kinds, missing parts and malformed parts', () {
      expect(visualFromInteraction({'kind': 'text', 'parts': []}), isNull);
      expect(visualFromInteraction({'kind': 'text_visual'}), isNull);
      expect(
          visualFromInteraction({
            'kind': 'text_visual',
            'parts': [
              {'type': 'visual', 'visual': 'oops'}
            ]
          }),
          isNull);
    });
  });
}
