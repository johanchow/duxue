import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// 答疑配图：服务端只给语义（有哪些对象、什么关系或数量），布局与绘制全在这里。
///
/// 契约与预算见 docs/technical/domain-tutoring-presentation.md §五。客户端不信任输入：
/// 先解析成纯 Dart 数据，任何一处类型或预算不对就整张图不画，文字照常显示，不报错、不弹窗。

/// 从 `companion-interaction.v1` 或 `CompanionMessage.interaction_ref` 取出配图；
/// 不是 `text_visual` 或没有 visual 时返回 null。
Map<String, dynamic>? visualFromInteraction(Map<String, dynamic> interaction) {
  if (interaction['kind'] != 'text_visual') return null;
  if (interaction['visual'] is Map) {
    return Map<String, dynamic>.from(interaction['visual'] as Map);
  }
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
              SvgData d => _SvgView(d),
            },
          ]),
        ),
      ),
    );
  }
}

// ---- 解析：预算与服务端一致，超出即整张不画 ------------------------------------------------

String? _str(Object? v, {int max = 120}) =>
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
      final alt = _str(raw['alt']);
      if (alt == null) return null;
      final title = _str(raw['title']);
      return switch (raw['kind']) {
        'steps' => StepsData.tryParse(raw, alt, title),
        'compare' => CompareData.tryParse(raw, alt, title),
        'segment' => SegmentData.tryParse(raw, alt, title),
        'number_line' => NumberLineData.tryParse(raw, alt, title),
        'svg' => SvgData.tryParse(raw, alt, title),
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
      final label = _str(item['label']);
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
      final t = _str(col['title']);
      final items = col['items'];
      if (t == null || items is! List || items.isEmpty || items.length > 4) {
        return null;
      }
      final texts = [for (final i in items) _str(i)];
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
      final parsed = [for (final l in rawLabels) _str(l)];
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
      final label = _str(bar['label']);
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
            label: _str(seg['label']), value: value, unknown: unknown));
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
          index, _str(b['label']), _num(b['value']), unknown));
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
        marks.add(NumberMark(label: _str(m['label']), unknown: true));
        continue;
      }
      final isPoint = at != null;
      final isInterval = start != null && end != null;
      if (isPoint == isInterval) return null;
      final values = [at, start, end].whereType<double>();
      if (values.any((v) => v < lo || v > hi)) return null;
      if (isInterval && start >= end) return null;
      marks.add(NumberMark(
          label: _str(m['label']),
          at: at,
          start: start,
          end: end,
          startClosed: m['start_closed'] != false,
          endClosed: m['end_closed'] != false));
    }
    return NumberLineData(lo, hi, step, marks, alt: alt, title: title);
  }
}

class SvgData extends VisualData {
  const SvgData(this.svg, this.height, this.texts,
      {required super.alt, super.title});
  final String svg;
  final double height;
  final List<String> texts;

  static const double canvasWidth = 680.0;
  static const int maxChars = 16000;

  static final RegExp _xmlComment = RegExp(r'<!--[\s\S]*?-->');
  static final RegExp _styleBlock = RegExp(
    r'<style\b[^>]*>[\s\S]*?</style>|<style\b[^>]*/>',
    caseSensitive: false,
  );
  static final RegExp _textBody = RegExp(
    r'(<(?:text|tspan|title|desc)\b[^>]*>)([\s\S]*?)(</(?:text|tspan|title|desc)>)',
    caseSensitive: false,
  );
  static final RegExp _rawAmp = RegExp(
    r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)',
  );
  static final RegExp _forbidden = RegExp(
    r'<!(?:DOCTYPE|ENTITY)|<\?xml|<(?:/?\s*(?:html|head|body|script|style|foreignObject|iframe|form|image|a)\b)'
    r'|/\*|position\s*:\s*fixed|\b(?:localStorage|sessionStorage|javascript:|data:)\b|https?:|www\.'
    r'|\bon[a-z]+\s*=|\b(?:href|src)\s*=',
    caseSensitive: false,
  );
  static final RegExp _viewBox = RegExp(
    r'''viewBox\s*=\s*(["'])\s*0(?:\.0+)?\s+0(?:\.0+)?\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s*\1''',
  );
  static final RegExp _shapeTag = RegExp(
    r'<\s*(?:rect|circle|ellipse|line|polyline|polygon|path)\b',
    caseSensitive: false,
  );
  static final RegExp _textTag = RegExp(
    r'<(?:text|title|desc)\b[^>]*>(.*?)</(?:text|title|desc)>',
    caseSensitive: false,
    dotAll: true,
  );
  static final RegExp _stripTags = RegExp(r'<[^>]+>');

  @override
  String get semanticLabel => [alt, ...texts].join('。');

  static String _escapeTextNodes(String input) =>
      input.replaceAllMapped(_textBody, (match) {
        final open = match.group(1)!;
        final body = match.group(2)!;
        final close = match.group(3)!;
        if (body.toLowerCase().contains('<tspan')) return match.group(0)!;
        final escaped = body
            .replaceAll(_rawAmp, '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;');
        return '$open$escaped$close';
      });

  static SvgData? tryParse(
      Map<String, dynamic> raw, String alt, String? title) {
    final svgObj = raw['svg'];
    if (svgObj is! String) return null;
    var code = _escapeTextNodes(
      svgObj.replaceAll(_xmlComment, '').replaceAll(_styleBlock, '').trim(),
    );
    if (code.length < 20 || code.length > maxChars) return null;
    if (_forbidden.hasMatch(code)) return null;
    final lower = code.toLowerCase();
    if (!lower.startsWith('<svg') || !lower.endsWith('</svg>')) return null;
    if (RegExp(r'<svg[\s>]', caseSensitive: false).allMatches(code).length != 1) {
      return null;
    }
    if (!_shapeTag.hasMatch(code)) return null;

    final vbMatch = _viewBox.firstMatch(code);
    if (vbMatch == null) return null;
    final width = double.tryParse(vbMatch.group(2)!);
    final h = double.tryParse(vbMatch.group(3)!);
    if (width == null || width <= 0 || h == null || h < 40 || h > 1600) {
      return null;
    }
    if ((width - canvasWidth).abs() > 0.01) {
      code = code.replaceFirst(vbMatch.group(0)!, 'viewBox="0 0 680 $h"');
    }

    final texts = <String>[];
    for (final m in _textTag.allMatches(code)) {
      final cleaned = m
          .group(1)!
          .replaceAll(_stripTags, ' ')
          .replaceAll(RegExp(r'\s+'), ' ')
          .trim();
      if (cleaned.isNotEmpty &&
          cleaned != alt &&
          cleaned != title &&
          (texts.isEmpty || texts.last != cleaned)) {
        texts.add(cleaned);
      }
    }
    return SvgData(code, h, texts, alt: alt, title: title);
  }
}

/// 将 SVG 中的宿主 CSS 变量（`var(--color-*)`）、`context-stroke` 以及浅色色阶摊平为当前明暗主题下的十六进制颜色。
String materializeSvgTheme(String svg, Brightness brightness) {
  final isDark = brightness == Brightness.dark;
  final vars = isDark ? _darkVars : _lightVars;
  var out = svg.replaceAllMapped(
    RegExp(r'var\(\s*--color-([a-z-]+)\s*\)'),
    (m) => vars[m.group(1)] ?? (isDark ? '#F2F1ED' : '#1A1A18'),
  );
  out = out.replaceAll('context-stroke', isDark ? '#B4B2A9' : '#888780');
  if (isDark) {
    out = out.replaceAllMapped(
      RegExp(r'#[0-9A-Fa-f]{6}\b'),
      (m) => _darkPaletteRemap[m.group(0)!.toUpperCase()] ?? m.group(0)!,
    );
  }
  return out;
}

const Map<String, String> _lightVars = {
  'background-primary': '#FFFFFF',
  'background-secondary': '#F7F7F5',
  'background-tertiary': '#EFEEEA',
  'background-info': '#E6F1FB',
  'background-danger': '#FCEBEB',
  'background-success': '#E1F5EE',
  'background-warning': '#FAEEDA',
  'text-primary': '#1A1A18',
  'text-secondary': '#5F5E5A',
  'text-tertiary': '#8A8983',
  'text-info': '#185FA5',
  'text-danger': '#A32D2D',
  'text-success': '#0F6E56',
  'text-warning': '#854F0B',
  'border-tertiary': '#D3D1C7',
  'border-secondary': '#B4B2A9',
  'border-primary': '#888780',
  'border-info': '#85B7EB',
  'border-danger': '#F09595',
  'border-success': '#5DCAA5',
  'border-warning': '#EF9F27',
};

const Map<String, String> _darkVars = {
  'background-primary': '#1C1C1A',
  'background-secondary': '#262624',
  'background-tertiary': '#333330',
  'background-info': '#0C447C',
  'background-danger': '#501313',
  'background-success': '#04342C',
  'background-warning': '#412402',
  'text-primary': '#F2F1ED',
  'text-secondary': '#B4B2A9',
  'text-tertiary': '#888780',
  'text-info': '#B5D4F4',
  'text-danger': '#F7C1C1',
  'text-success': '#9FE1CB',
  'text-warning': '#FAC775',
  'border-tertiary': '#444441',
  'border-secondary': '#5F5E5A',
  'border-primary': '#888780',
  'border-info': '#378ADD',
  'border-danger': '#E24B4A',
  'border-success': '#1D9E75',
  'border-warning': '#BA7517',
};

// 深色模式下将 9 色系 50 浅底色 / 800 深字色自动翻转为 800 深底色 / 100 浅字色（见 draw-02-how.md 色板规则）
const Map<String, String> _darkPaletteRemap = {
  // 50 fills -> 800 fills
  '#EEEDFE': '#3C3489',
  '#E1F5EE': '#085041',
  '#FAECE7': '#712B13',
  '#FBEAF0': '#72243E',
  '#F1EFE8': '#444441',
  '#E6F1FB': '#0C447C',
  '#EAF3DE': '#27500A',
  '#FAEEDA': '#633806',
  '#FCEBEB': '#791F1F',
  // 800/900 text -> 100 light text
  '#3C3489': '#CECBF6',
  '#26215C': '#CECBF6',
  '#085041': '#9FE1CB',
  '#04342C': '#9FE1CB',
  '#712B13': '#F5C4B3',
  '#4A1B0C': '#F5C4B3',
  '#72243E': '#F4C0D1',
  '#4B1528': '#F4C0D1',
  '#0C447C': '#B5D4F4',
  '#042C53': '#B5D4F4',
  '#27500A': '#C0DD97',
  '#173404': '#C0DD97',
  '#633806': '#FAC775',
  '#412402': '#FAC775',
  '#791F1F': '#F7C1C1',
  '#501313': '#F7C1C1',
};

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

class _SvgView extends StatelessWidget {
  const _SvgView(this.data);
  final SvgData data;

  static const double _maxDisplayHeight = 560.0;

  @override
  Widget build(BuildContext context) {
    final brightness = Theme.of(context).brightness;
    final themed = materializeSvgTheme(data.svg, brightness);
    return LayoutBuilder(builder: (context, constraints) {
      final width = constraints.maxWidth.isFinite && constraints.maxWidth > 0
          ? constraints.maxWidth
          : SvgData.canvasWidth;
      final naturalHeight = width * (data.height / SvgData.canvasWidth);
      final height = naturalHeight.clamp(40.0, _maxDisplayHeight);
      return SizedBox(
        key: const ValueKey('svg-visual-view'),
        width: width,
        height: height,
        child: SvgPicture.string(
          themed,
          width: width,
          height: height,
          fit: BoxFit.contain,
        ),
      );
    });
  }
}
