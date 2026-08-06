import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/models.dart';
import '../providers.dart';

class ReportPage extends ConsumerStatefulWidget {
  const ReportPage({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<ReportPage> createState() => _ReportPageState();
}

class _ReportPageState extends ConsumerState<ReportPage> {
  DateTime selected = DateTime.now();
  static const colors = {
    '学习': Color(0xff22c55e),
    '走神/玩耍': Color(0xfff59e0b),
    '离开': Color(0xff94a3b8),
  };
  @override
  Widget build(BuildContext context) {
    final report = ref.watch(
      reportProvider((wardId: widget.wardId, date: selected)),
    );
    return Scaffold(
      appBar: AppBar(title: const Text('日报')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: OutlinedButton.icon(
              onPressed: () async {
                final date = await showDatePicker(
                  context: context,
                  initialDate: selected,
                  firstDate: DateTime(2020),
                  lastDate: DateTime.now(),
                );
                if (date != null) setState(() => selected = date);
              },
              icon: const Icon(Icons.calendar_today),
              label: Text(
                '${selected.year}-${selected.month.toString().padLeft(2, '0')}-${selected.day.toString().padLeft(2, '0')}',
              ),
            ),
          ),
          Expanded(
            child: report.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(child: Text('加载失败：$e')),
              data: (data) {
                if (data.status != 'ready') {
                  return Center(
                    child: Text(
                      data.status == 'processing' ? '分析中，报告将在次日就绪' : '当天没有监控数据',
                    ),
                  );
                }
                return ListView(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                  children: [
                    if (data.profileChanged)
                      const Card(
                        color: Color(0xfffffbeb),
                        child: Padding(
                          padding: EdgeInsets.all(12),
                          child: Text('本报告基于修改前的分析配置生成'),
                        ),
                      ),
                    SizedBox(
                      height: 220,
                      child: PieChart(
                        PieChartData(
                          centerSpaceRadius: 48,
                          sections: data.breakdown.entries
                              .map(
                                (entry) => PieChartSectionData(
                                  value: entry.value.toDouble(),
                                  title:
                                      '${entry.key}\n${(entry.value / data.totalSeconds * 100).round()}%',
                                  color: colors[entry.key] ?? Colors.blue,
                                  radius: 72,
                                ),
                              )
                              .toList(),
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),
                    Text('时间轴', style: Theme.of(context).textTheme.titleLarge),
                    const SizedBox(height: 8),
                    SizedBox(
                      height: 70,
                      child: CustomPaint(
                        painter: TimelinePainter(data.timeline, colors),
                      ),
                    ),
                    ...data.timeline.map(
                      (segment) => ListTile(
                        dense: true,
                        leading: CircleAvatar(
                          radius: 6,
                          backgroundColor: colors[segment.label] ?? Colors.blue,
                        ),
                        title: Text(segment.label),
                        subtitle: Text(
                          '${TimeOfDay.fromDateTime(segment.start.toLocal()).format(context)} – ${TimeOfDay.fromDateTime(segment.end.toLocal()).format(context)}',
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class WeeklyTrendPage extends ConsumerStatefulWidget {
  const WeeklyTrendPage({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<WeeklyTrendPage> createState() => _WeeklyTrendPageState();
}

class _WeeklyTrendPageState extends ConsumerState<WeeklyTrendPage> {
  DateTime endDate = DateTime.now();
  @override
  Widget build(BuildContext context) {
    final trend = ref.watch(
      weeklyTrendProvider((wardId: widget.wardId, endDate: endDate)),
    );
    return Scaffold(
      appBar: AppBar(title: const Text('近 7 天趋势')),
      body: trend.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(child: Text('加载失败：$error')),
        data: (data) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            OutlinedButton.icon(
              onPressed: () async {
                final date = await showDatePicker(
                  context: context,
                  initialDate: endDate,
                  firstDate: DateTime(2020),
                  lastDate: DateTime.now(),
                );
                if (date != null) setState(() => endDate = date);
              },
              icon: const Icon(Icons.calendar_today),
              label: Text(
                '截至 ${endDate.year}-${endDate.month.toString().padLeft(2, '0')}-${endDate.day.toString().padLeft(2, '0')}',
              ),
            ),
            const SizedBox(height: 24),
            SizedBox(height: 250, child: _TrendChart(days: data.days)),
            const SizedBox(height: 16),
            const Row(
              children: [
                Icon(Icons.circle, size: 10, color: Color(0xff22c55e)),
                SizedBox(width: 6),
                Text('学习时长'),
              ],
            ),
            const SizedBox(height: 12),
            ...data.days.map(
              (day) => Card(
                child: ListTile(
                  title: Text('${day.date.month}月${day.date.day}日'),
                  trailing: Text(_duration(day.learningSeconds)),
                  subtitle: Text('总监控 ${_duration(day.totalSeconds)}'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  static String _duration(int seconds) =>
      seconds < 60 ? '$seconds秒' : '${seconds ~/ 60}分';
}

class _TrendChart extends StatelessWidget {
  const _TrendChart({required this.days});
  final List<WeeklyTrendDay> days;
  @override
  Widget build(BuildContext context) => LineChart(
        LineChartData(
          minY: 0,
          gridData: const FlGridData(show: true),
          titlesData: FlTitlesData(
            topTitles:
                const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            rightTitles: const AxisTitles(
              sideTitles: SideTitles(showTitles: false),
            ),
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 46,
                getTitlesWidget: (value, _) => Text(
                  _WeeklyTrendPageState._duration(value.toInt()),
                  style: const TextStyle(fontSize: 10),
                ),
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                getTitlesWidget: (value, _) {
                  final index = value.toInt();
                  if (index < 0 || index >= days.length) {
                    return const SizedBox();
                  }
                  final day = days[index].date;
                  return Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      '${day.month}/${day.day}',
                      style: const TextStyle(fontSize: 10),
                    ),
                  );
                },
              ),
            ),
          ),
          lineBarsData: [
            LineChartBarData(
              isCurved: true,
              color: const Color(0xff22c55e),
              barWidth: 3,
              dotData: const FlDotData(show: true),
              spots: [
                for (var i = 0; i < days.length; i++)
                  FlSpot(i.toDouble(), days[i].learningSeconds.toDouble()),
              ],
            ),
          ],
        ),
      );
}

class TimelinePainter extends CustomPainter {
  TimelinePainter(this.segments, this.colors);
  final List<Segment> segments;
  final Map<String, Color> colors;
  @override
  void paint(Canvas canvas, Size size) {
    if (segments.isEmpty) return;
    final start = segments.first.start.millisecondsSinceEpoch;
    final end = segments.last.end.millisecondsSinceEpoch;
    final span = (end - start).clamp(1, 1 << 62);
    for (final segment in segments) {
      final left =
          (segment.start.millisecondsSinceEpoch - start) / span * size.width;
      final right =
          (segment.end.millisecondsSinceEpoch - start) / span * size.width;
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTRB(left, 12, right, size.height - 12),
          const Radius.circular(5),
        ),
        Paint()..color = colors[segment.label] ?? Colors.blue,
      );
    }
  }

  @override
  bool shouldRepaint(covariant TimelinePainter oldDelegate) =>
      oldDelegate.segments != segments;
}
