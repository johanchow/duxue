import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:markdown/markdown.dart' as md;

/// 伴学消息气泡专用的轻量安全 Markdown + TeX 渲染组件。
///
/// 遵循 `docs/assistant-markdown-body-contract.md` 与未成年人安全边界：
/// - 支持 GFM 段落、粗体/斜体、列表、引用、行内与围栏代码块、紧凑横滑表格；
/// - 4 项生成式容错扩展：单换行 `\n` 保真换行、`<br>`/`<br/>` 转换行、
///   严格双波浪线 `~~` 删除线（避免 `1~10` 误变删除线）、宽松 `**粗体**`；
/// - 行内公式 `$...$` / `\(...\)`（`MathStyle.text`）与块级公式 `$$...$$` / `\[...\]`
///   （`MathStyle.display` + 横向 `SingleChildScrollView`），解析失败回退显示源码；
/// - 压平标题层级（仅加粗、字号贴近正文）；
/// - 禁用外链跳转、自动 URL 识别与外部网络图片加载（链接与图片仅渲染纯文本）。
class ChatMarkdownBody extends StatelessWidget {
  const ChatMarkdownBody({
    super.key,
    required this.text,
    this.style,
  });

  final String text;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final defaultStyle = DefaultTextStyle.of(context).style;
    final baseStyle = defaultStyle.merge(
      TextStyle(
        fontSize: 14,
        height: 1.45,
        color: isDark ? const Color(0xFFE2E8F0) : const Color(0xFF0F172A),
      ),
    ).merge(style);

    final nodes = _parseMarkdown(text);
    final palette = _MarkdownPalette.fromBrightness(isDark, baseStyle);
    final blocks = _BlockRenderer(palette: palette).renderBlocks(nodes);
    if (blocks.isEmpty) {
      return Text(text, style: baseStyle);
    }
    if (blocks.length == 1) {
      return blocks.first;
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < blocks.length; i++) ...[
          if (i > 0) const SizedBox(height: 6),
          blocks[i],
        ],
      ],
    );
  }
}

List<md.Node> _parseMarkdown(String source) {
  final normalized = source.replaceAll('\r\n', '\n');
  final document = md.Document(
    encodeHtml: false,
    withDefaultBlockSyntaxes: false,
    withDefaultInlineSyntaxes: false,
    blockSyntaxes: [
      const md.FencedCodeBlockSyntax(),
      const md.HeaderWithIdSyntax(),
      const md.SetextHeaderWithIdSyntax(),
      const md.TableSyntax(),
      const md.UnorderedListWithCheckboxSyntax(),
      const md.OrderedListWithCheckboxSyntax(),
      const md.UnorderedListSyntax(),
      const md.OrderedListSyntax(),
      const md.BlockquoteSyntax(),
      const md.HorizontalRuleSyntax(),
      const md.ParagraphSyntax(),
    ],
    inlineSyntaxes: [
      md.CodeSyntax(),
      _DisplayBracketMathInlineSyntax(),
      _InlineParenMathSyntax(),
      md.EscapeSyntax(),
      _DisplayDollarMathInlineSyntax(),
      _InlineDollarMathSyntax(),
      _BrTagSyntax(),
      _StrictStrikethroughSyntax(),
      _LenientBoldSyntax(),
      _SafeImageSyntax(),
      _SafeLinkSyntax(),
      md.EmphasisSyntax.underscore(),
      md.EmphasisSyntax.asterisk(),
    ],
  );
  return document.parseLines(normalized.split('\n'));
}

/// 段落内嵌或独占行的 `$$...$$` 块级公式。
class _DisplayDollarMathInlineSyntax extends md.InlineSyntax {
  _DisplayDollarMathInlineSyntax() : super(r'\$\$([\s\S]+?)\$\$');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final latex = (match[1] ?? '').trim();
    if (latex.isEmpty) {
      return false;
    }
    parser.addNode(md.Element.text('tex-block', latex));
    return true;
  }
}

/// 段落内嵌的 `\[...\]` 块级公式。
class _DisplayBracketMathInlineSyntax extends md.InlineSyntax {
  _DisplayBracketMathInlineSyntax() : super(r'\\\[([\s\S]+?)\\\]');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final latex = (match[1] ?? '').trim();
    if (latex.isEmpty) {
      return false;
    }
    parser.addNode(md.Element.text('tex-block', latex));
    return true;
  }
}

/// 行内 `\(...\)` 公式。
class _InlineParenMathSyntax extends md.InlineSyntax {
  _InlineParenMathSyntax() : super(r'\\\(([^\n]+?)\\\)');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final latex = (match[1] ?? '').trim();
    if (latex.isEmpty) {
      return false;
    }
    parser.addNode(md.Element.text('tex-inline', latex));
    return true;
  }
}

/// 行内 `$...$` 公式：单行、闭合、首尾无多余空白，且闭合 `$` 后不紧跟数字。
/// 不满足条件时返回 false，保留原 `$` 字符。
class _InlineDollarMathSyntax extends md.InlineSyntax {
  _InlineDollarMathSyntax()
      : super(r'(?<!\$)\$(?!\$)(?!\s)([^\$\n]+?)(?<!\s)\$(?!\$)(?!\d)');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final latex = match[1] ?? '';
    if (latex.isEmpty) {
      return false;
    }
    parser.addNode(md.Element.text('tex-inline', latex));
    return true;
  }
}

/// `<br>` / `<br/>` / `<br />` 容错换行扩展。
class _BrTagSyntax extends md.InlineSyntax {
  _BrTagSyntax() : super(r'<\s*br\s*/?\s*>', caseSensitive: false);

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    parser.addNode(md.Element.empty('br'));
    return true;
  }
}

/// 严格删除线：仅识别双波浪线 `~~...~~`，不识别单波浪线 `~`（防止 `1~10` 被划掉）。
class _StrictStrikethroughSyntax extends md.InlineSyntax {
  _StrictStrikethroughSyntax() : super(r'~~(?=\S)([\s\S]*?\S)~~');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final inner = match[1] ?? '';
    parser.addNode(md.Element.text('del', inner));
    return true;
  }
}

/// 宽松 `**粗体**` 容错：兼容 `**内容 **` 尾部空格与中文全角标点相邻边界。
class _LenientBoldSyntax extends md.InlineSyntax {
  _LenientBoldSyntax() : super(r'(?<!\*)\*\*(?=\S)([^\n*]+?)\*\*(?!\*)');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final inner = (match[1] ?? '').trimRight();
    if (inner.isEmpty) {
      return false;
    }
    final element = md.Element('strong', parser.document.parseInline(inner));
    parser.addNode(element);
    return true;
  }
}

/// 未成年人安全边界：Markdown 内联图片 `![alt](url)` 仅展示纯文本，不拉取外部图片。
class _SafeImageSyntax extends md.InlineSyntax {
  _SafeImageSyntax() : super(r'!\[([^\]]*)\]\(([^)\n]+)\)');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final alt = (match[1] ?? '').trim();
    parser.addNode(md.Text(alt.isEmpty ? '[图片]' : alt));
    return true;
  }
}

/// 未成年人安全边界：Markdown 链接 `[text](url)` 仅展示可读文本，不绑定外链跳转。
class _SafeLinkSyntax extends md.InlineSyntax {
  _SafeLinkSyntax() : super(r'\[([^\]]+)\]\(([^)\n]+)\)');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final label = (match[1] ?? '').trim();
    parser.addNode(md.Text(label));
    return true;
  }
}

class _MarkdownPalette {
  const _MarkdownPalette({
    required this.baseStyle,
    required this.codeBackground,
    required this.codeBorder,
    required this.codeText,
    required this.quoteBorder,
    required this.quoteText,
    required this.tableHeaderBackground,
    required this.tableBorder,
  });

  factory _MarkdownPalette.fromBrightness(bool isDark, TextStyle baseStyle) {
    if (isDark) {
      return _MarkdownPalette(
        baseStyle: baseStyle,
        codeBackground: const Color(0xFF1E293B),
        codeBorder: const Color(0xFF334155),
        codeText: const Color(0xFFE2E8F0),
        quoteBorder: const Color(0xFF64748B),
        quoteText: const Color(0xFFCBD5E1),
        tableHeaderBackground: const Color(0xFF1E293B),
        tableBorder: const Color(0xFF475569),
      );
    }
    return _MarkdownPalette(
      baseStyle: baseStyle,
      codeBackground: const Color(0xFFEFF6FF),
      codeBorder: const Color(0xFFCBD5E1),
      codeText: const Color(0xFF1E293B),
      quoteBorder: const Color(0xFF94A3B8),
      quoteText: const Color(0xFF475569),
      tableHeaderBackground: const Color(0xFFF1F5F9),
      tableBorder: const Color(0xFFCBD5E1),
    );
  }

  final TextStyle baseStyle;
  final Color codeBackground;
  final Color codeBorder;
  final Color codeText;
  final Color quoteBorder;
  final Color quoteText;
  final Color tableHeaderBackground;
  final Color tableBorder;
}

class _BlockRenderer {
  const _BlockRenderer({required this.palette});

  final _MarkdownPalette palette;

  List<Widget> renderBlocks(List<md.Node> nodes) {
    final widgets = <Widget>[];
    for (final node in nodes) {
      if (node is md.Text) {
        final trimmed = node.text.trim();
        if (trimmed.isNotEmpty) {
          widgets.add(Text(trimmed, style: palette.baseStyle));
        }
        continue;
      }
      if (node is! md.Element) {
        continue;
      }
      switch (node.tag) {
        case 'p':
          widgets.addAll(_renderParagraphOrMixedBlocks(node.children ?? const []));
          break;
        case 'h1':
        case 'h2':
        case 'h3':
        case 'h4':
        case 'h5':
        case 'h6':
          // 压平标题层级：仅加粗、字号贴近正文，防止撑破伴学气泡
          final baseSize = palette.baseStyle.fontSize ?? 14;
          final headingSize =
              (node.tag == 'h1' || node.tag == 'h2') ? baseSize + 1 : baseSize;
          final headingStyle = palette.baseStyle.copyWith(
            fontSize: headingSize,
            fontWeight: FontWeight.w700,
          );
          widgets.add(_buildRichText(node.children ?? const [], headingStyle));
          break;
        case 'tex-block':
          widgets.add(_buildDisplayMath(node.textContent));
          break;
        case 'pre':
          widgets.add(_buildCodeBlock(node.textContent));
          break;
        case 'blockquote':
          widgets.add(_buildBlockquote(node.children ?? const []));
          break;
        case 'ul':
          widgets.add(_buildList(node.children ?? const [], ordered: false));
          break;
        case 'ol':
          final start = int.tryParse(node.attributes['start'] ?? '1') ?? 1;
          widgets.add(
            _buildList(node.children ?? const [], ordered: true, start: start),
          );
          break;
        case 'table':
          widgets.add(_buildTable(node));
          break;
        case 'hr':
          widgets.add(Divider(height: 12, thickness: 1, color: palette.tableBorder));
          break;
        default:
          widgets.add(_buildRichText(node.children ?? [md.Text(node.textContent)], palette.baseStyle));
      }
    }
    return widgets;
  }

  /// 若段落内部嵌有 `tex-block`（如未留空行的 `$$...$$`），将其拆分为独立横滑块级公式与富文本段落。
  List<Widget> _renderParagraphOrMixedBlocks(List<md.Node> children) {
    final hasBlockMath =
        children.any((n) => n is md.Element && n.tag == 'tex-block');
    if (!hasBlockMath) {
      return [_buildRichText(children, palette.baseStyle)];
    }
    final result = <Widget>[];
    final inlineBuffer = <md.Node>[];
    void flushInline() {
      if (inlineBuffer.isEmpty) {
        return;
      }
      final trimmed = _trimLeadingTrailingNewlines(inlineBuffer);
      if (trimmed.isNotEmpty) {
        result.add(_buildRichText(trimmed, palette.baseStyle));
      }
      inlineBuffer.clear();
    }

    for (final child in children) {
      if (child is md.Element && child.tag == 'tex-block') {
        flushInline();
        result.add(_buildDisplayMath(child.textContent));
      } else {
        inlineBuffer.add(child);
      }
    }
    flushInline();
    return result;
  }

  List<md.Node> _trimLeadingTrailingNewlines(List<md.Node> nodes) {
    final copy = List<md.Node>.of(nodes);
    if (copy.isNotEmpty && copy.first is md.Text) {
      final firstText = (copy.first as md.Text).text.replaceFirst(RegExp(r'^\n+'), '');
      if (firstText.isEmpty) {
        copy.removeAt(0);
      } else {
        copy[0] = md.Text(firstText);
      }
    }
    if (copy.isNotEmpty && copy.last is md.Text) {
      final lastText = (copy.last as md.Text).text.replaceFirst(RegExp(r'\n+$'), '');
      if (lastText.isEmpty) {
        copy.removeLast();
      } else {
        copy[copy.length - 1] = md.Text(lastText);
      }
    }
    return copy;
  }

  Widget _buildDisplayMath(String latex) {
    final style = palette.baseStyle;
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Math.tex(
          latex,
          mathStyle: MathStyle.display,
          textStyle: style,
          onErrorFallback: (_) => Text(latex, style: style),
        ),
      ),
    );
  }

  Widget _buildCodeBlock(String code) {
    final trimmed = code.endsWith('\n') ? code.substring(0, code.length - 1) : code;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: palette.codeBackground,
        border: Border.all(color: palette.codeBorder),
        borderRadius: BorderRadius.circular(8),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Text(
          trimmed,
          style: palette.baseStyle.copyWith(
            fontFamily: 'monospace',
            fontSize: (palette.baseStyle.fontSize ?? 14) - 1,
            color: palette.codeText,
          ),
        ),
      ),
    );
  }

  Widget _buildBlockquote(List<md.Node> children) {
    final inner = _BlockRenderer(
      palette: _MarkdownPalette(
        baseStyle: palette.baseStyle.copyWith(color: palette.quoteText),
        codeBackground: palette.codeBackground,
        codeBorder: palette.codeBorder,
        codeText: palette.codeText,
        quoteBorder: palette.quoteBorder,
        quoteText: palette.quoteText,
        tableHeaderBackground: palette.tableHeaderBackground,
        tableBorder: palette.tableBorder,
      ),
    ).renderBlocks(children);

    return Container(
      padding: const EdgeInsets.only(left: 10, top: 2, bottom: 2),
      decoration: BoxDecoration(
        border: Border(left: BorderSide(color: palette.quoteBorder, width: 3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: inner,
      ),
    );
  }

  Widget _buildList(
    List<md.Node> items, {
    required bool ordered,
    int start = 1,
  }) {
    final rows = <Widget>[];
    var index = start;
    for (final item in items) {
      if (item is! md.Element || item.tag != 'li') {
        continue;
      }
      final marker = ordered ? '$index. ' : '• ';
      index++;
      final itemChildren = item.children ?? const [];
      Widget contentWidget;
      if (itemChildren.any((n) => n is md.Element && (n.tag == 'p' || n.tag == 'ul' || n.tag == 'ol'))) {
        final nested = renderBlocks(itemChildren);
        contentWidget = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: nested,
        );
      } else {
        contentWidget = _buildRichText(itemChildren, palette.baseStyle);
      }
      rows.add(
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 1.5),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(marker, style: palette.baseStyle.copyWith(fontWeight: FontWeight.w600)),
              Expanded(child: contentWidget),
            ],
          ),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: rows,
    );
  }

  Widget _buildTable(md.Element tableElement) {
    final rows = <TableRow>[];
    var maxCols = 0;
    final parsedRows = <(bool isHeader, List<md.Element> cells)>[];

    for (final section in tableElement.children ?? const <md.Node>[]) {
      if (section is! md.Element) {
        continue;
      }
      final isHeader = section.tag == 'thead';
      for (final tr in section.children ?? const <md.Node>[]) {
        if (tr is! md.Element || tr.tag != 'tr') {
          continue;
        }
        final cells = (tr.children ?? const <md.Node>[])
            .whereType<md.Element>()
            .where((e) => e.tag == 'th' || e.tag == 'td')
            .toList();
        if (cells.length > maxCols) {
          maxCols = cells.length;
        }
        parsedRows.add((isHeader, cells));
      }
    }

    if (maxCols == 0) {
      return const SizedBox.shrink();
    }

    for (final (isHeader, cells) in parsedRows) {
      final cellStyle = isHeader
          ? palette.baseStyle.copyWith(fontWeight: FontWeight.w700)
          : palette.baseStyle;
      rows.add(
        TableRow(
          decoration: isHeader
              ? BoxDecoration(color: palette.tableHeaderBackground)
              : null,
          children: [
            for (var col = 0; col < maxCols; col++)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                child: col < cells.length
                    ? _buildRichText(cells[col].children ?? const [], cellStyle)
                    : const SizedBox.shrink(),
              ),
          ],
        ),
      );
    }

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Table(
        defaultColumnWidth: const IntrinsicColumnWidth(),
        border: TableBorder.all(color: palette.tableBorder, width: 1),
        defaultVerticalAlignment: TableCellVerticalAlignment.middle,
        children: rows,
      ),
    );
  }

  Widget _buildRichText(List<md.Node> nodes, TextStyle style) {
    final spans = _buildInlineSpans(nodes, style);
    if (spans.length == 1 && spans.first is TextSpan) {
      final single = spans.first as TextSpan;
      if ((single.children == null || single.children!.isEmpty) &&
          single.style == style) {
        return Text(single.text ?? '', style: style);
      }
    }
    return Text.rich(
      TextSpan(style: style, children: spans),
    );
  }

  List<InlineSpan> _buildInlineSpans(List<md.Node> nodes, TextStyle currentStyle) {
    final spans = <InlineSpan>[];
    for (final node in nodes) {
      if (node is md.Text) {
        // softLineBreak 保真：保留单个 `\n` 作为真换行
        spans.add(TextSpan(text: node.text, style: currentStyle));
        continue;
      }
      if (node is! md.Element) {
        continue;
      }
      switch (node.tag) {
        case 'br':
          spans.add(TextSpan(text: '\n', style: currentStyle));
          break;
        case 'strong':
          final boldStyle = currentStyle.copyWith(fontWeight: FontWeight.w700);
          spans.addAll(_buildInlineSpans(node.children ?? const [], boldStyle));
          break;
        case 'em':
          final italicStyle = currentStyle.copyWith(fontStyle: FontStyle.italic);
          spans.addAll(_buildInlineSpans(node.children ?? const [], italicStyle));
          break;
        case 'del':
          final delStyle = currentStyle.copyWith(
            decoration: TextDecoration.lineThrough,
          );
          spans.addAll(_buildInlineSpans(node.children ?? [md.Text(node.textContent)], delStyle));
          break;
        case 'code':
          spans.add(
            TextSpan(
              text: node.textContent,
              style: currentStyle.copyWith(
                fontFamily: 'monospace',
                backgroundColor: palette.codeBackground,
                color: palette.codeText,
              ),
            ),
          );
          break;
        case 'tex-inline':
          final latex = node.textContent;
          spans.add(
            WidgetSpan(
              alignment: PlaceholderAlignment.middle,
              child: Math.tex(
                latex,
                mathStyle: MathStyle.text,
                textStyle: currentStyle,
                onErrorFallback: (_) => Text(latex, style: currentStyle),
              ),
            ),
          );
          break;
        case 'tex-block':
          final latex = node.textContent;
          spans.add(
            WidgetSpan(
              alignment: PlaceholderAlignment.middle,
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Math.tex(
                  latex,
                  mathStyle: MathStyle.display,
                  textStyle: currentStyle,
                  onErrorFallback: (_) => Text(latex, style: currentStyle),
                ),
              ),
            ),
          );
          break;
        default:
          spans.addAll(
            _buildInlineSpans(
              node.children ?? [md.Text(node.textContent)],
              currentStyle,
            ),
          );
      }
    }
    return spans;
  }
}
