import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers.dart';

final eveningReportProvider = FutureProvider.autoDispose.family<
    Map<String, dynamic>,
    ({String wardId, DateTime date, int? version})>((ref, key) async {
  return ref
      .watch(apiProvider)
      .eveningReport(key.wardId, key.date, version: key.version);
});

const observationActivityNames = {
  'writing': '书写',
  'reading_material': '阅读材料',
  'handling_material': '整理材料',
  'still_with_material': '面对材料静止',
  'other_visible_activity': '其他可见活动',
  'away': '离座',
  'unknown': '无法判断',
  'missing': '缺少图片',
};

class EveningReportCard extends ConsumerStatefulWidget {
  const EveningReportCard(
      {required this.wardId, required this.date, super.key});
  final String wardId;
  final DateTime date;
  @override
  ConsumerState<EveningReportCard> createState() => _EveningReportCardState();
}

class _EveningReportCardState extends ConsumerState<EveningReportCard> {
  int? version;
  int latest = 0;
  @override
  void didUpdateWidget(EveningReportCard old) {
    super.didUpdateWidget(old);
    if (old.wardId != widget.wardId || old.date != widget.date) {
      version = null;
      latest = 0;
    }
  }

  @override
  Widget build(BuildContext context) {
    final key = (wardId: widget.wardId, date: widget.date, version: version);
    return ref.watch(eveningReportProvider(key)).when(
          loading: () => const LinearProgressIndicator(),
          error: (_, __) => TextButton(
              onPressed: () => ref.invalidate(eveningReportProvider(key)),
              child: const Text('重试晚间报告')),
          data: (data) {
            if (data['status'] == 'pending') return const SizedBox.shrink();
            final current = data['version'] as int;
            if (version == null) latest = current;
            final observation = data['observation'] as Map?;
            final totals = observation?['totals'] as Map? ?? {};
            final coverage = observation?['coverage'] as Map?;
            final ratio = coverage?['ratio'] as num?;
            return Card(
                child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('晚间实况 · 第 $current 版',
                            style: Theme.of(context).textTheme.titleMedium),
                        Text(data['summary'] as String? ?? ''),
                        Text('报告截止：${data['cutoff_at']}'),
                        Text(ratio == null
                            ? '采集覆盖率暂不可确定'
                            : '采集覆盖率 ${(ratio * 100).toStringAsFixed(0)}%'),
                        for (final entry in totals.entries)
                          Text(
                              '${observationActivityNames[entry.key] ?? '其他'}：约 ${((entry.value as num) ~/ 60)} 分钟'),
                        if (data['status'] == 'partial')
                          const Text('部分证据缺失；不将缺失时段算作不专注。'),
                        if (latest > 1)
                          DropdownButton<int>(
                              value: current,
                              items: [
                                for (var number = latest; number >= 1; number--)
                                  DropdownMenuItem(
                                      value: number,
                                      child: Text('第 $number 版')),
                              ],
                              onChanged: (value) =>
                                  setState(() => version = value)),
                      ],
                    )));
          },
        );
  }
}
