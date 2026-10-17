import 'package:duxue_app/shared/chat_markdown.dart';
import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_test/flutter_test.dart';

Widget _wrap(
  Widget child, {
  Brightness brightness = Brightness.light,
  double textScale = 1.0,
  double width = 300,
}) =>
    MaterialApp(
      theme: ThemeData(brightness: brightness, useMaterial3: true),
      home: MediaQuery(
        data: MediaQueryData(textScaler: TextScaler.linear(textScale)),
        child: Scaffold(
          body: Center(
            child: SizedBox(width: width, child: child),
          ),
        ),
      ),
    );

void main() {
  testWidgets('renders inline math with dollar and paren delimiters as MathStyle.text', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: r'分式 $\frac{1}{3} + \frac{1}{6} = \frac{1}{2}$ 与根号 \(\sqrt{x^2 + 1}\) 都能显示。',
        ),
      ),
    );

    final mathWidgets = tester.widgetList<Math>(find.byType(Math)).toList();
    expect(mathWidgets.length, 2);
    expect(mathWidgets[0].mathStyle, MathStyle.text);
    expect(mathWidgets[1].mathStyle, MathStyle.text);
    expect(tester.takeException(), isNull);
  });

  testWidgets('does not treat spaced dollars, currency, or escaped dollars as math', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: r'金额 $ 100 $ 或单价 \$5 都不是公式。',
        ),
      ),
    );

    expect(find.byType(Math), findsNothing);
    expect(find.text(r'金额 $ 100 $ 或单价 $5 都不是公式。'), findsOneWidget);
  });

  testWidgets('renders display math blocks inside horizontal SingleChildScrollView', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: '联立方程：\n\$\$\n\\begin{cases} x + y = 10 \\\\ x - y = 2 \\end{cases}\n\$\$\n以及 \\[a^2 + b^2 = c^2\\]',
        ),
      ),
    );

    final mathWidgets = tester.widgetList<Math>(find.byType(Math)).toList();
    expect(mathWidgets.length, 2);
    for (final m in mathWidgets) {
      expect(m.mathStyle, MathStyle.display);
    }
    expect(find.byType(SingleChildScrollView), findsNWidgets(2));
    expect(tester.takeException(), isNull);
  });

  testWidgets('invalid TeX and unclosed math fences fall back to plain text without throwing', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: '坏公式 \$\\frac{1}{\$ 与未闭合块 \$\$x + 1',
        ),
      ),
    );
    await tester.pump();

    expect(tester.takeException(), isNull);
    expect(find.text(r'\frac{1}{'), findsOneWidget);
    expect(find.textContaining(r'$$x + 1'), findsOneWidget);
  });

  testWidgets('strict strikethrough keeps 1~10 intact while striking ~~error~~', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: '范围是 1~10，把 ~~错误步骤~~ 划掉。',
        ),
      ),
    );

    final textWidget = tester.widget<Text>(find.byType(Text).first);
    final rootSpan = textWidget.textSpan! as TextSpan;
    final spans = rootSpan.children!.whereType<TextSpan>().toList();

    expect(
      spans.any((s) => (s.text ?? '').contains('1~10') && s.style?.decoration != TextDecoration.lineThrough),
      isTrue,
    );
    expect(
      spans.any((s) => s.text == '错误步骤' && s.style?.decoration == TextDecoration.lineThrough),
      isTrue,
    );
  });

  testWidgets('lenient bold handles trailing spaces and full-width Chinese punctuation', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: '先看**（一）已知条件**，再看**重点 **部分。',
        ),
      ),
    );

    final textWidget = tester.widget<Text>(find.byType(Text).first);
    final rootSpan = textWidget.textSpan! as TextSpan;
    final boldTexts = <String>[];
    void collectBold(InlineSpan span) {
      if (span is TextSpan) {
        if (span.style?.fontWeight == FontWeight.w700 && (span.text ?? '').isNotEmpty) {
          boldTexts.add(span.text!);
        }
        for (final child in span.children ?? const <InlineSpan>[]) {
          collectBold(child);
        }
      }
    }

    collectBold(rootSpan);
    expect(boldTexts, containsAll(['（一）已知条件', '重点']));
  });

  testWidgets('converts <br> tags and preserves single newline softLineBreak', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: '第一行\n第二行<br>第三行<br/>第四行',
        ),
      ),
    );

    final textWidget = tester.widget<Text>(find.byType(Text).first);
    final plain = textWidget.textSpan!.toPlainText();
    expect(plain, '第一行\n第二行\n第三行\n第四行');
  });

  testWidgets('renders pipe tables with horizontal scroll and flattens headings', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: '# 小结\n\n| 概念 | 公式 |\n| --- | --- |\n| 速度 | \$v = \\frac{s}{t}\$<br>单位 m/s |',
        ),
      ),
    );

    expect(find.text('小结'), findsOneWidget);
    expect(find.byType(Table), findsOneWidget);
    expect(find.byType(Math), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('blocks external links and markdown images as plain text for minor safety', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: '请看 [外部网站](https://example.com) 和 ![示意图](https://example.com/a.png)。',
        ),
      ),
    );

    expect(find.byType(Image), findsNothing);
    expect(find.text('请看 外部网站 和 示意图。'), findsOneWidget);

    final textWidget = tester.widget<Text>(find.byType(Text).first);
    bool hasRecognizer(InlineSpan span) {
      if (span is TextSpan) {
        if (span.recognizer != null) return true;
        return (span.children ?? const []).any(hasRecognizer);
      }
      return false;
    }

    if (textWidget.textSpan != null) {
      expect(hasRecognizer(textWidget.textSpan!), isFalse);
    }
  });

  testWidgets('adapts to dark mode and 1.3x text scale without layout overflow', (tester) async {
    await tester.pumpWidget(
      _wrap(
        const ChatMarkdownBody(
          text: '已知 \$a+b=5\$：\n- 第一步\n- 第二步\n\n```python\nx = 1 + 2\n```',
        ),
        brightness: Brightness.dark,
        textScale: 1.3,
        width: 260,
      ),
    );
    await tester.pump();

    expect(tester.takeException(), isNull);
    expect(find.byType(Math), findsOneWidget);
  });
}
