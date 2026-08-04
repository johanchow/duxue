import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/models.dart';
import '../providers.dart';

class ReportPage extends ConsumerStatefulWidget { const ReportPage({required this.ward, super.key}); final Ward ward; @override ConsumerState<ReportPage> createState() => _ReportPageState(); }
class _ReportPageState extends ConsumerState<ReportPage> {
  DateTime selected = DateTime.now();
  static const colors = {'学习': Color(0xff22c55e), '走神/玩耍': Color(0xfff59e0b), '离开': Color(0xff94a3b8)};
  @override Widget build(BuildContext context) {
    final report = ref.watch(reportProvider((wardId: widget.ward.id, date: selected)));
    return Scaffold(appBar: AppBar(title: Text('${widget.ward.displayName} · 日报')), body: report.when(loading: () => const Center(child: CircularProgressIndicator()), error: (e, _) => Center(child: Text('加载失败：$e')), data: (data) {
      if (data.status != 'ready') return Center(child: Text(data.status == 'processing' ? '分析中，报告将在次日就绪' : '当天没有监控数据'));
      return ListView(padding: const EdgeInsets.all(16), children: [
        if (data.profileChanged) const Card(color: Color(0xfffffbeb), child: Padding(padding: EdgeInsets.all(12), child: Text('本报告基于修改前的分析配置生成'))),
        SizedBox(height: 220, child: PieChart(PieChartData(centerSpaceRadius: 48, sections: data.breakdown.entries.map((entry) => PieChartSectionData(value: entry.value.toDouble(), title: '${entry.key}\n${(entry.value / data.totalSeconds * 100).round()}%', color: colors[entry.key] ?? Colors.blue, radius: 72)).toList()))),
        const SizedBox(height: 24), Text('时间轴', style: Theme.of(context).textTheme.titleLarge), const SizedBox(height: 8),
        SizedBox(height: 70, child: CustomPaint(painter: TimelinePainter(data.timeline, colors))),
        ...data.timeline.map((segment) => ListTile(dense: true, leading: CircleAvatar(radius: 6, backgroundColor: colors[segment.label] ?? Colors.blue), title: Text(segment.label), subtitle: Text('${TimeOfDay.fromDateTime(segment.start.toLocal()).format(context)} – ${TimeOfDay.fromDateTime(segment.end.toLocal()).format(context)}'))),
      ]);
    }));
  }
}

class TimelinePainter extends CustomPainter {
  TimelinePainter(this.segments, this.colors); final List<Segment> segments; final Map<String, Color> colors;
  @override void paint(Canvas canvas, Size size) {
    if (segments.isEmpty) return; final start = segments.first.start.millisecondsSinceEpoch; final end = segments.last.end.millisecondsSinceEpoch; final span = (end - start).clamp(1, 1 << 62);
    for (final segment in segments) { final left = (segment.start.millisecondsSinceEpoch - start) / span * size.width; final right = (segment.end.millisecondsSinceEpoch - start) / span * size.width; canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTRB(left, 12, right, size.height - 12), const Radius.circular(5)), Paint()..color = colors[segment.label] ?? Colors.blue); }
  }
  @override bool shouldRepaint(covariant TimelinePainter oldDelegate) => oldDelegate.segments != segments;
}
