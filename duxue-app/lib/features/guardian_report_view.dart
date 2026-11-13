import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/models.dart';
import '../providers.dart';
import '../shared/chat_markdown.dart';
import 'evening_report_card.dart';

DateTime guardianToday() {
  final day = DateTime.now().toUtc().add(const Duration(hours: 8));
  return DateTime(day.year, day.month, day.day);
}

final tutoringEvidenceProvider = FutureProvider.autoDispose
    .family<List<Map<String, dynamic>>, ({String wardId, DateTime date})>(
        (ref, key) =>
            ref.watch(apiProvider).tutoringEvidence(key.wardId, key.date));
final _evidenceDetailProvider = FutureProvider.autoDispose.family<
        Map<String, dynamic>,
        ({String wardId, DateTime date, String problemId})>(
    (ref, key) => ref
        .watch(apiProvider)
        .tutoringEvidenceDetail(key.wardId, key.date, key.problemId));

/// Report and teaching evidence are independent reads. No generation or mastery inference.
class GuardianReportView extends ConsumerStatefulWidget {
  const GuardianReportView({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<GuardianReportView> createState() => _GuardianReportViewState();
}

class _GuardianReportViewState extends ConsumerState<GuardianReportView>
    with WidgetsBindingObserver {
  DateTime today = guardianToday();
  late DateTime selected = today;
  Timer? refreshTimer;
  bool foreground = true;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    refreshTimer = Timer.periodic(const Duration(minutes: 1), (_) {
      if (foreground) _refresh();
    });
  }

  @override
  void dispose() {
    refreshTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didUpdateWidget(GuardianReportView old) {
    super.didUpdateWidget(old);
    if (old.wardId != widget.wardId) {
      selected = today = guardianToday();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    foreground = state == AppLifecycleState.resumed;
    if (!foreground) return;
    final current = guardianToday();
    setState(() {
      if (selected == today) selected = current;
      today = current;
    });
    _refresh();
  }

  Future<void> _refresh() async {
    if (!mounted || !foreground) return;
    final current = guardianToday();
    if (current != today) {
      setState(() {
        if (selected == today) selected = current;
        today = current;
      });
    }
    final key = (wardId: widget.wardId, date: selected);
    ref.invalidate(eveningReportProvider);
    ref.invalidate(reportProvider(key));
    ref.invalidate(tutoringEvidenceProvider(key));
    ref.invalidate(_evidenceDetailProvider);
    try {
      await Future.wait([
        ref.read(reportProvider(key).future),
        ref.read(tutoringEvidenceProvider(key).future),
      ]);
    } catch (_) {
      // Each section presents its own error and retry; retain the other section.
    }
  }

  Future<void> _history() async {
    final date = await showDatePicker(
      context: context,
      initialDate: selected,
      firstDate: DateTime(2020),
      lastDate: guardianToday(),
    );
    if (date != null && mounted) setState(() => selected = date);
  }

  @override
  Widget build(BuildContext context) {
    final key = (wardId: widget.wardId, date: selected);
    final report = ref.watch(reportProvider(key));
    final evidence = ref.watch(tutoringEvidenceProvider(key));
    final evening = ref.watch(eveningReportProvider(
        (wardId: widget.wardId, date: selected, version: null)));
    final hasEvening = evening.valueOrNull?['version'] != null;
    final titleStyle = Theme.of(context)
        .textTheme
        .titleLarge
        ?.copyWith(fontWeight: FontWeight.w700);
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        key: ValueKey('guardian-report-${widget.wardId}-$selected'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
        children: [
          Row(children: [
            Expanded(
                child: Text(
                    '${selected == today ? '今天 · ' : ''}${selected.month}月${selected.day}日',
                    style: Theme.of(context).textTheme.titleMedium)),
            TextButton(onPressed: _history, child: const Text('历史')),
          ]),
          const Divider(height: 24),
          EveningReportCard(wardId: widget.wardId, date: selected),
          if (!hasEvening) Text('学习报告', style: titleStyle),
          const SizedBox(height: 12),
          if (!hasEvening)
            report.when(
              skipLoadingOnRefresh: false,
              loading: () => const Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(child: CircularProgressIndicator())),
              error: (_, __) => _ReadError(
                  '报告加载失败', '重试报告', () => ref.invalidate(reportProvider(key))),
              data: (data) => _ReportContent(report: data),
            ),
          evidence.when(
            skipLoadingOnRefresh: false,
            loading: () => const Padding(
                padding: EdgeInsets.only(top: 24),
                child: LinearProgressIndicator()),
            error: (_, __) => Padding(
                padding: const EdgeInsets.only(top: 24),
                child: _ReadError('解题凭证加载失败', '重试凭证',
                    () => ref.invalidate(tutoringEvidenceProvider(key)))),
            data: (items) => items.isEmpty
                ? const SizedBox.shrink()
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Divider(height: 36),
                      Text('独立解题凭证', style: titleStyle),
                      const SizedBox(height: 12),
                      for (final item in items)
                        Padding(
                            padding: const EdgeInsets.only(bottom: 12),
                            child: _ThinkingEvidence(
                                key: ValueKey(
                                    '${widget.wardId}-$selected-${item['id']}'),
                                wardId: widget.wardId,
                                date: selected,
                                item: item)),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

class _ReportContent extends StatelessWidget {
  const _ReportContent({required this.report});
  final DailyReport report;
  String _duration(int seconds) => seconds < 60
      ? '$seconds秒'
      : '${seconds ~/ 60}分钟${seconds % 60 == 0 ? '' : '${seconds % 60}秒'}';
  String _clock(DateTime instant) {
    final local = instant.toUtc().add(const Duration(hours: 8));
    return '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    if (report.status != 'ready') {
      return Padding(
          padding: const EdgeInsets.symmetric(vertical: 36),
          child: Column(children: [
            Icon(Icons.description_outlined,
                size: 42, color: Theme.of(context).colorScheme.outline),
            const SizedBox(height: 12),
            Text(report.status == 'processing' ? '正在整理学习报告' : '报告尚未生成',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
                report.status == 'processing'
                    ? '学习记录整理后，会直接显示在这里。'
                    : '有学习记录后，会在这里整理呈现。',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium),
          ]));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('根据观察记录整理', style: Theme.of(context).textTheme.bodySmall),
      const SizedBox(height: 16),
      if (report.profileChanged) ...[
        const Text('这份报告使用的是修改前的观察配置。'),
        const SizedBox(height: 12),
      ],
      if (report.breakdown.isEmpty && report.timeline.isEmpty)
        const Text('报告已生成，当前没有可展示的观察片段。')
      else ...[
        const Text('本日记录到的活动：', style: TextStyle(height: 1.6)),
        for (final entry in report.breakdown.entries)
          Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('${entry.key}：${_duration(entry.value)}',
                  style: const TextStyle(height: 1.6))),
        if (report.timeline.isNotEmpty) ...[
          const SizedBox(height: 20),
          Text('观察过程', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 8),
          for (final segment in report.timeline)
            Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Text(
                    '${_clock(segment.start)}—${_clock(segment.end)}  ${segment.label}')),
        ],
        const SizedBox(height: 16),
        Text('以上为观察到的活动记录，不代表作业完成情况或知识掌握程度。',
            style:
                Theme.of(context).textTheme.bodySmall?.copyWith(height: 1.5)),
      ],
    ]);
  }
}

class _ThinkingEvidence extends ConsumerStatefulWidget {
  const _ThinkingEvidence(
      {required this.wardId,
      required this.date,
      required this.item,
      super.key});
  final String wardId;
  final DateTime date;
  final Map<String, dynamic> item;
  @override
  ConsumerState<_ThinkingEvidence> createState() => _ThinkingEvidenceState();
}

class _ThinkingEvidenceState extends ConsumerState<_ThinkingEvidence> {
  bool expanded = false;
  @override
  Widget build(BuildContext context) {
    final key = (
      wardId: widget.wardId,
      date: widget.date,
      problemId: widget.item['id'] as String
    );
    final detail = expanded ? ref.watch(_evidenceDetailProvider(key)) : null;
    return Card(
      margin: EdgeInsets.zero,
      color: Theme.of(context)
          .colorScheme
          .secondaryContainer
          .withValues(alpha: .35),
      clipBehavior: Clip.antiAlias,
      child: ExpansionTile(
        shape: const Border(),
        collapsedShape: const Border(),
        title: Text(widget.item['title'] as String,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(expanded ? '收起思考过程' : '展开思考过程'),
        onExpansionChanged: (value) => setState(() => expanded = value),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        children: [
          if (detail != null)
            detail.when(
              loading: () => const Padding(
                  padding: EdgeInsets.all(16),
                  child: CircularProgressIndicator()),
              error: (_, __) => _ReadError('思考过程加载失败', '重试过程',
                  () => ref.invalidate(_evidenceDetailProvider(key))),
              data: (data) => Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final message in (data['messages'] as List))
                      Padding(
                          padding: const EdgeInsets.only(top: 14),
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                    message['role'] == 'ward'
                                        ? (message['kind'] == 'attempt'
                                            ? '孩子的尝试'
                                            : '孩子的问题')
                                        : '引导与回应',
                                    style: Theme.of(context)
                                        .textTheme
                                        .labelMedium),
                                const SizedBox(height: 4),
                                ChatMarkdownBody(
                                    text: message['content'] as String),
                              ])),
                    const SizedBox(height: 16),
                    Text('保留本题的引导与尝试；尚无独立核验结论。',
                        style: Theme.of(context).textTheme.bodySmall),
                  ]),
            )
        ],
      ),
    );
  }
}

class _ReadError extends StatelessWidget {
  const _ReadError(this.message, this.action, this.retry);
  final String message;
  final String action;
  final VoidCallback retry;
  @override
  Widget build(BuildContext context) =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(message),
        TextButton(onPressed: retry, child: Text(action)),
      ]);
}
