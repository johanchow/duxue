import 'dart:math' as math;

import 'package:flutter/material.dart';

/// 答疑配图：服务端只给语义（有哪些对象、什么关系或数量），布局与绘制全在这里。
///
/// 契约与预算见 docs/technical/domain-tutoring-presentation.md §五。客户端不信任输入：
/// 先解析成纯 Dart 数据，任何一处类型或预算不对就整张图不画，文字照常显示，不报错、不弹窗。

/// 从 `companion-interaction.v1` 取出配图；不是 `text_visual` 或没有 visual part 时返回 null。
Map<String, dynamic>? visualFromInteraction(Map<String, dynamic> interaction) {
  if (interaction['kind'] != 'text_visual') return null;
  final parts = interaction['parts'];
  if (parts is! List) return null;
  for (final part in parts) {
    if (part is Map && part['type'] == 'visual' && part['visual'] is Map) {
      return Map<String, dynamic>.from(part['visual'] as Map);
    }
  }
  return null;
}

class VisualBlock extends StatelessWidget {
  const VisualBlock({required this.visual, super.key});

  final Map<String, dynamic> visual;

  @override
  Widget build(BuildContext context) {
    final data = VisualData.tryParse(visual);
    if (data == null) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      container: true,
      label: data.semanticLabel,
      child: ExcludeSemantics(
        child: Container(
          key: const ValueKey('visual-block'),
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: scheme.surfaceContainerHighest.withValues(alpha: 0.4),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: scheme.outlineVariant),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (data.title != null) ...[
              Text(data.title!,
                  style: const TextStyle(
                      fontSize: 14, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
            ],
            switch (data) {
              StepsData d => _StepsView(d),
              CompareData d => _CompareView(d),
              SegmentData d => _SegmentView(d),
              NumberLineData d => _NumberLineView(d),
            },
          ]),
        ),
      ),
    );
  }
}

// ---- 解析：预算与服务端一致，超出即整张不画 ------------------------------------------------

String? _str(Object? v, {int max = 40}) =>
    v is String && v.trim().isNotEmpty && v.length <= max ? v.trim() : null;

double? _num(Object? v) => v is num && v.isFinite ? v.toDouble() : null;

List<Map<String, dynamic>>? _maps(Object? v, int min, int max) {
  if (v is! List || v.length < min || v.length > max) return null;
  final out = <Map<String, dynamic>>[];
  for (final item in v) {
    if (item is! Map) return null;
    out.add(Map<String, dynamic>.from(item));
  }
  return out;
}

sealed class VisualData {
  const VisualData({required this.alt, this.title});
  final String alt;
  final String? title;

  String get semanticLabel;

  static VisualData? tryParse(Map<String, dynamic> raw) {
    try {
      final alt = _str(raw['alt'], max: 120);
      if (alt == null) return null;
      final title = _str(raw['title'], max: 20);
      return switch (raw['kind']) {
        'steps' => StepsData.tryParse(raw, alt, title),
        'compare' => CompareData.tryParse(raw, alt, title),
        'segment' => SegmentData.tryParse(raw, alt, title),
        'number_line' => NumberLineData.tryParse(raw, alt, title),
        _ => null, // 词汇表之外：降级为只有文字
      };
    } catch (_) {
      return null;
    }
  }
}

class StepsData extends VisualData {
  const StepsData(this.steps, {required super.alt, super.title});
  final List<({String label, String? detail})> steps;

  @override
  String get semanticLabel => [
        alt,
        for (var i = 0; i < steps.length; i++)
          '第${i + 1}步，${steps[i].label}${steps[i].detail == null ? '' : '，${steps[i].detail}'}',
      ].join('。');

  static StepsData? tryParse(Map<String, dynamic> raw, String alt, String? title) {
    final items = _maps(raw['steps'], 2, 5);
    if (items == null) return null;
    final steps = <({String label, String? detail})>[];
    for (final item in items) {
      final label = _str(item['label'], max: 24);
      if (label == null) return null;
      steps.add((label: label, detail: _str(item['detail'])));
    }
    return StepsData(steps, alt: alt, title: title);
  }
}

class CompareData extends VisualData {
  const CompareData(this.titles, this.columns, this.rowLabels,
      {required super.alt, super.title});
  final List<String> titles;
  final List<List<String>> columns;
  final List<String>? rowLabels;

  int get rows => columns.first.length;

  @override
  String get semanticLabel => [
        alt,
        for (var c = 0; c < titles.length; c++)
          '${titles[c]}：${columns[c].join('，')}',
      ].join('。');

  static CompareData? tryParse(Map<String, dynamic> raw, String alt, String? title) {
    final cols = _maps(raw['columns'], 2, 3);
    if (cols == null) return null;
    final titles = <String>[];
    final columns = <List<String>>[];
    for (final col in cols) {
      final t = _str(col['title'], max: 12);
      final items = col['items'];
      if (t == null || items is! List || items.isEmpty || items.length > 4) {
        return null;
      }
      final texts = [for (final i in items) _str(i, max: 24)];
      if (texts.contains(null)) return null;
      titles.add(t);
      columns.add(texts.cast<String>());
    }
    if (columns.map((c) => c.length).toSet().length != 1) return null;
    List<String>? labels;
    final rawLabels = raw['row_labels'];
    if (rawLabels != null) {
      if (rawLabels is! List || rawLabels.length != columns.first.length) {
        return null;
      }
      final parsed = [for (final l in rawLabels) _str(l, max: 12)];
      if (parsed.contains(null)) return null;
      labels = parsed.cast<String>();
    }
    return CompareData(titles, columns, labels, alt: alt, title: title);
  }
}

class SegmentPart {
  const SegmentPart({this.label, this.value, this.unknown = false});
  final String? label;
  final double? value;
  final bool unknown;
}

class SegmentBar {
  const SegmentBar(this.label, this.parts);
  final String label;
  final List<SegmentPart> parts;
}

class SegmentBracket {
  const SegmentBracket(this.bar, this.label, this.value, this.unknown);
  final int bar;
  final String? label;
  final double? value;
  final bool unknown;
}

class SegmentData extends VisualData {
  const SegmentData(this.bars, this.brackets, {required super.alt, super.title});
  final List<SegmentBar> bars;
  final List<SegmentBracket> brackets;

  @override
  String get semanticLabel => alt;

  static SegmentData? tryParse(Map<String, dynamic> raw, String alt, String? title) {
    final rawBars = _maps(raw['bars'], 1, 4);
    if (rawBars == null) return null;
    final bars = <SegmentBar>[];
    for (final bar in rawBars) {
      final label = _str(bar['label'], max: 12);
      final segs = _maps(bar['segments'], 1, 6);
      if (label == null || segs == null) return null;
      final parts = <SegmentPart>[];
      for (final seg in segs) {
        final value = _num(seg['value']);
        final unknown = seg['unknown'] == true;
        // 未知量不带数值：收到带数值的未知量，宁可不画。
        if (unknown && (seg['value'] != null)) return null;
        if (value != null && value < 0) return null;
        parts.add(SegmentPart(
            label: _str(seg['label'], max: 12), value: value, unknown: unknown));
      }
      bars.add(SegmentBar(label, parts));
    }
    final rawBrackets = raw['brackets'] == null ? <Map<String, dynamic>>[] : _maps(raw['brackets'], 0, 2);
    if (rawBrackets == null) return null;
    final brackets = <SegmentBracket>[];
    for (final b in rawBrackets) {
      final index = b['bar'];
      final unknown = b['unknown'] == true;
      if (index is! int || index < 0 || index >= bars.length) return null;
      if (unknown && b['value'] != null) return null;
      brackets.add(SegmentBracket(
          index, _str(b['label'], max: 12), _num(b['value']), unknown));
    }
    return SegmentData(bars, brackets, alt: alt, title: title);
  }
}

class NumberMark {
  const NumberMark(
      {this.label,
      this.at,
      this.start,
      this.end,
      this.startClosed = true,
      this.endClosed = true,
      this.unknown = false});
  final String? label;
  final double? at;
  final double? start;
  final double? end;
  final bool startClosed;
  final bool endClosed;
  final bool unknown;
}

class NumberLineData extends VisualData {
  const NumberLineData(this.min, this.max, this.step, this.marks,
      {required super.alt, super.title});
  final double min;
  final double max;
  final double step;
  final List<NumberMark> marks;

  @override
  String get semanticLabel => alt;

  static NumberLineData? tryParse(Map<String, dynamic> raw, String alt, String? title) {
    final lo = _num(raw['min']);
    final hi = _num(raw['max']);
    final step = _num(raw['step']);
    if (lo == null || hi == null || step == null) return null;
    if (!(hi > lo) || !(step > 0) || (hi - lo) / step > 20.0001) return null;
    final rawMarks = raw['marks'] == null ? <Map<String, dynamic>>[] : _maps(raw['marks'], 0, 8);
    if (rawMarks == null) return null;
    final marks = <NumberMark>[];
    for (final m in rawMarks) {
      final unknown = m['unknown'] == true;
      final at = _num(m['at']);
      final start = _num(m['start']);
      final end = _num(m['end']);
      if (unknown) {
        if (at != null || start != null || end != null) return null;
        marks.add(NumberMark(label: _str(m['label'], max: 10), unknown: true));
        continue;
      }
      final isPoint = at != null;
      final isInterval = start != null && end != null;
      if (isPoint == isInterval) return null;
      final values = [at, start, end].whereType<double>();
      if (values.any((v) => v < lo || v > hi)) return null;
      if (isInterval && start >= end) return null;
      marks.add(NumberMark(
          label: _str(m['label'], max: 10),
          at: at,
          start: start,
          end: end,
          startClosed: m['start_closed'] != false,
          endClosed: m['end_closed'] != false));
    }
    return NumberLineData(lo, hi, step, marks, alt: alt, title: title);
  }
}

// ---- 绘制 -----------------------------------------------------------------------------------

class _StepsView extends StatelessWidget {
  const _StepsView(this.data);
  final StepsData data;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(children: [
      for (var i = 0; i < data.steps.length; i++) ...[
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 26,
            height: 26,
            alignment: Alignment.center,
            decoration:
                BoxDecoration(color: scheme.primary, shape: BoxShape.circle),
            child: Text('${i + 1}',
                style: TextStyle(
                    color: scheme.onPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w700)),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(data.steps[i].label,
                        style: const TextStyle(
                            fontSize: 14, fontWeight: FontWeight.w600)),
                    if (data.steps[i].detail != null)
                      Text(data.steps[i].detail!,
                          style: TextStyle(
                              fontSize: 12, color: scheme.onSurfaceVariant)),
                  ]),
            ),
          ),
        ]),
        if (i < data.steps.length - 1)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Align(
                alignment: Alignment.centerLeft,
                child: Padding(
                    padding: const EdgeInsets.only(left: 4),
                    child: Icon(Icons.arrow_downward,
                        size: 18, color: scheme.outline))),
          ),
      ],
    ]);
  }
}

class _CompareView extends StatelessWidget {
  const _CompareView(this.data);
  final CompareData data;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final hasLabels = data.rowLabels != null;
    Widget cell(String text, {bool header = false, Color? color}) => Container(
          color: color,
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          child: Text(text,
              style: TextStyle(
                  fontSize: header ? 13 : 12.5,
                  fontWeight: header ? FontWeight.w700 : FontWeight.w400)),
        );
    return Table(
      border: TableBorder.all(color: scheme.outlineVariant),
      defaultColumnWidth: const FlexColumnWidth(),
      columnWidths: hasLabels ? const {0: IntrinsicColumnWidth()} : null,
      children: [
        TableRow(children: [
          if (hasLabels) cell('', color: scheme.primaryContainer),
          for (final t in data.titles)
            cell(t, header: true, color: scheme.primaryContainer),
        ]),
        for (var r = 0; r < data.rows; r++)
          TableRow(children: [
            if (hasLabels) cell(data.rowLabels![r], header: true),
            for (final column in data.columns) cell(column[r]),
          ]),
      ],
    );
  }
}

class _SegmentView extends StatelessWidget {
  const _SegmentView(this.data);
  final SegmentData data;

  static const _unknownUnits = 2.0; // 未知量没有数值，画一段固定的示意长度
  static const _labelWidth = 56.0;

  double _units(SegmentBar bar) => bar.parts.fold<double>(
      0,
      (sum, p) =>
          sum + (p.unknown ? _unknownUnits : (p.value ?? 1).clamp(0.5, 1e6)));

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return LayoutBuilder(builder: (context, constraints) {
      final trackWidth = math.max(60.0, constraints.maxWidth - _labelWidth - 8);
      final widest = data.bars.map(_units).reduce(math.max);
      final unit = trackWidth / widest;
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (var i = 0; i < data.bars.length; i++) ...[
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(
                width: _labelWidth + 8,
                child: Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(data.bars[i].label,
                        style: const TextStyle(
                            fontSize: 13, fontWeight: FontWeight.w600)))),
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                for (final part in data.bars[i].parts)
                  _segment(context, part, unit, scheme),
              ]),
              for (final bracket in data.brackets.where((b) => b.bar == i))
                _bracket(bracket, _units(data.bars[i]) * unit, scheme),
            ]),
          ]),
          const SizedBox(height: 10),
        ],
      ]);
    });
  }

  Widget _segment(BuildContext context, SegmentPart part, double unit, ColorScheme scheme) {
    final width = (part.unknown ? _unknownUnits : (part.value ?? 1).clamp(0.5, 1e6)) * unit;
    final text = part.unknown
        ? '${part.label ?? ''}?'
        : [part.label, if (part.value != null) _fmt(part.value!)]
            .whereType<String>()
            .join(' ');
    return Container(
      key: part.unknown ? const ValueKey('segment-unknown') : null,
      width: width,
      height: 30,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: part.unknown ? Colors.transparent : scheme.primaryContainer,
        border: Border.all(
            color: part.unknown ? scheme.error : scheme.primary,
            width: part.unknown ? 1.5 : 1),
      ),
      child: Text(text,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
              fontSize: 12,
              color: part.unknown ? scheme.error : scheme.onPrimaryContainer)),
    );
  }

  Widget _bracket(SegmentBracket bracket, double width, ColorScheme scheme) {
    final amount = bracket.unknown ? '?' : (bracket.value == null ? '' : _fmt(bracket.value!));
    return SizedBox(
      width: width,
      child: Column(children: [
        Container(
          height: 8,
          decoration: BoxDecoration(
              border: Border(
                  left: BorderSide(color: scheme.outline),
                  right: BorderSide(color: scheme.outline),
                  bottom: BorderSide(color: scheme.outline))),
        ),
        Text('${bracket.label ?? ''}$amount',
            style: TextStyle(
                fontSize: 12,
                color: bracket.unknown ? scheme.error : scheme.onSurface)),
      ]),
    );
  }
}

String _fmt(double v) => v == v.roundToDouble() ? v.round().toString() : v.toString();

class _NumberLineView extends StatelessWidget {
  const _NumberLineView(this.data);
  final NumberLineData data;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final unknown = data.marks.where((m) => m.unknown).toList();
    final scaler = MediaQuery.textScalerOf(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(
        width: double.infinity,
        height: 78 * math.max(1.0, scaler.scale(1)),
        child: CustomPaint(
          key: const ValueKey('number-line-paint'),
          painter: _NumberLinePainter(
            data,
            axis: scheme.outline,
            accent: scheme.primary,
            text: scheme.onSurface,
            background: scheme.surface,
            scaler: scaler,
          ),
        ),
      ),
      if (unknown.isNotEmpty)
        Wrap(spacing: 8, children: [
          for (final m in unknown)
            Chip(
              key: const ValueKey('number-line-unknown'),
              visualDensity: VisualDensity.compact,
              label: Text('? ${m.label ?? ''} 位置待求',
                  style: TextStyle(fontSize: 12, color: scheme.error)),
            ),
        ]),
    ]);
  }
}

class _NumberLinePainter extends CustomPainter {
  _NumberLinePainter(this.data,
      {required this.axis,
      required this.accent,
      required this.text,
      required this.background,
      required this.scaler});

  final NumberLineData data;
  final Color axis;
  final Color accent;
  final Color text;
  final Color background;
  final TextScaler scaler;

  @override
  void paint(Canvas canvas, Size size) {
    const pad = 16.0;
    final y = size.height * 0.55;
    final width = size.width - pad * 2;
    double x(double v) => pad + (v - data.min) / (data.max - data.min) * width;

    final axisPaint = Paint()
      ..color = axis
      ..strokeWidth = 2;
    canvas.drawLine(Offset(pad - 6, y), Offset(size.width - pad + 6, y), axisPaint);

    final count = ((data.max - data.min) / data.step).round();
    final every = count > 10 ? 2 : 1;
    for (var i = 0; i <= count; i++) {
      final v = data.min + i * data.step;
      final tx = x(v);
      canvas.drawLine(Offset(tx, y - 5), Offset(tx, y + 5), axisPaint);
      if (i % every == 0) {
        _label(canvas, _fmt(double.parse(v.toStringAsFixed(6))), Offset(tx, y + 8), 11, text);
      }
    }

    final mark = Paint()..color = accent;
    final line = Paint()
      ..color = accent
      ..strokeWidth = 5
      ..strokeCap = StrokeCap.butt;
    for (final m in data.marks.where((m) => !m.unknown)) {
      if (m.at != null) {
        canvas.drawCircle(Offset(x(m.at!), y), 6, mark);
        if (m.label != null) {
          _label(canvas, m.label!, Offset(x(m.at!), y - 30), 12, accent, bold: true);
        }
      } else {
        final a = x(m.start!), b = x(m.end!);
        canvas.drawLine(Offset(a, y), Offset(b, y), line);
        for (final (cx, closed) in [(a, m.startClosed), (b, m.endClosed)]) {
          canvas.drawCircle(Offset(cx, y), 6, closed ? mark : (Paint()..color = background));
          if (!closed) {
            canvas.drawCircle(
                Offset(cx, y),
                6,
                Paint()
                  ..color = accent
                  ..style = PaintingStyle.stroke
                  ..strokeWidth = 2);
          }
        }
        if (m.label != null) {
          _label(canvas, m.label!, Offset((a + b) / 2, y - 30), 12, accent, bold: true);
        }
      }
    }
  }

  void _label(Canvas canvas, String s, Offset anchor, double size, Color color,
      {bool bold = false}) {
    final painter = TextPainter(
      text: TextSpan(
          text: s,
          style: TextStyle(
              fontSize: size,
              color: color,
              fontWeight: bold ? FontWeight.w700 : FontWeight.w400)),
      textDirection: TextDirection.ltr,
      textScaler: scaler,
    )..layout();
    painter.paint(canvas, anchor - Offset(painter.width / 2, 0));
  }

  @override
  bool shouldRepaint(_NumberLinePainter old) =>
      old.data != data || old.axis != axis || old.accent != accent || old.scaler != scaler;
}
