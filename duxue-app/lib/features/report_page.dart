import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/models.dart';
import '../core/user_error_message.dart';
import 'guardian_report_view.dart';
import '../providers.dart';

class ReportPage extends StatelessWidget {
  const ReportPage({required this.wardId, super.key});
  final String wardId;
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('学习报告')),
        body: GuardianReportView(wardId: wardId),
      );
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
        error: (error, _) =>
            Center(child: Text('加载趋势失败：${userErrorMessage(error)}')),
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
