import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';
import '../../shared/chat_markdown.dart';
import 'math_stage_view.dart';

/// Adult MentorCourseware page (P0-1):
/// - Phase 1 fast verification summary + collapsible outline
/// - Interactive MathStageView per step with single-step static fallback
/// - Dialogue-based localized revision (pinning target_step_id)
/// - Millisecond Undo / Redo (allowed even while a revision is in-flight)
class GuardianCoursewarePage extends ConsumerStatefulWidget {
  const GuardianCoursewarePage({
    required this.promptText,
    this.attachmentKeys = const [],
    this.initialCoursewareId,
    super.key,
  });

  final String promptText;
  final List<String> attachmentKeys;
  final String? initialCoursewareId;

  @override
  ConsumerState<GuardianCoursewarePage> createState() =>
      _GuardianCoursewarePageState();
}

class _GuardianCoursewarePageState
    extends ConsumerState<GuardianCoursewarePage> {
  final _revisionInput = TextEditingController();
  Timer? _pollTimer;
  String? _coursewareId;
  Map<String, dynamic>? _view;
  Map<String, dynamic>? _status;
  String? _error;
  String? _pinnedStepId;
  final Set<String> _expandedStepIds = {};
  bool _deckMode = false;
  int _deckIndex = 0;
  int _cmdSeq = 0;
  bool _movingCursor = false;

  String _nextCmdId(String prefix) =>
      '$prefix-${DateTime.now().microsecondsSinceEpoch}-${++_cmdSeq}';

  @override
  void initState() {
    super.initState();
    _coursewareId = widget.initialCoursewareId;
    unawaited(_bootstrap());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _revisionInput.dispose();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    try {
      final api = ref.read(apiProvider);
      if (_coursewareId == null) {
        final created = await api.createMentorCourseware(
          commandId: _nextCmdId('create'),
          promptText: widget.promptText,
          attachmentKeys: widget.attachmentKeys,
        );
        if (!mounted) return;
        _coursewareId = created['courseware_id'] as String?;
      }
      await _refresh();
      _ensurePolling();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '深度课件启动失败，请重试。');
    }
  }

  void _ensurePolling() {
    _pollTimer?.cancel();
    final st = _view?['status'] as String?;
    final revPending = _view?['active_revision_pending'] == true;
    if (st == 'drafting' || revPending) {
      _pollTimer = Timer.periodic(
        const Duration(milliseconds: 1200),
        (_) => unawaited(_refresh()),
      );
    }
  }

  Future<void> _refresh() async {
    final cid = _coursewareId;
    if (cid == null) return;
    try {
      final api = ref.read(apiProvider);
      final view = await api.getMentorCourseware(cid);
      final status = await api.getMentorCoursewareStatus(cid);
      if (!mounted) return;
      setState(() {
        _view = view;
        _status = status;
        _error = null;
        final steps = _steps;
        if (steps.isNotEmpty && _expandedStepIds.isEmpty) {
          _expandedStepIds.add(steps.first['step_id'] as String);
        }
        if (_deckIndex >= steps.length && steps.isNotEmpty) {
          _deckIndex = steps.length - 1;
        }
      });
      if (view['status'] != 'drafting' &&
          view['active_revision_pending'] != true) {
        _pollTimer?.cancel();
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = '读取课件状态失败，请点击重试。');
    }
  }

  List<Map<String, dynamic>> get _steps {
    final cv = _view?['current_version'];
    if (cv is! Map) return const [];
    return ((cv['steps'] as List?) ?? const [])
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
  }

  Future<void> _sendRevision() async {
    final cid = _coursewareId;
    final view = _view;
    final text = _revisionInput.text.trim();
    if (cid == null || view == null || text.isEmpty) return;
    final cv = view['current_version'] as Map?;
    if (cv == null) return;

    _revisionInput.clear();
    try {
      final api = ref.read(apiProvider);
      await api.requestMentorCoursewareRevision(
        coursewareId: cid,
        commandId: _nextCmdId('rev'),
        instruction: text,
        baseVersionNo: cv['version_no'] as int,
        expectedStateRevision: view['state_revision'] as int,
        targetStepId: _pinnedStepId,
      );
      if (!mounted) return;
      setState(() => _pinnedStepId = null);
      await _refresh();
      _ensurePolling();
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = '提交修订失败，请稍后重试。');
    }
  }

  Future<void> _moveCursor({required bool undo}) async {
    final cid = _coursewareId;
    final view = _view;
    if (cid == null || view == null || _movingCursor) return;
    setState(() => _movingCursor = true);
    try {
      final api = ref.read(apiProvider);
      final updated = undo
          ? await api.undoMentorCourseware(
              coursewareId: cid,
              commandId: _nextCmdId('undo'),
              expectedStateRevision: view['state_revision'] as int,
            )
          : await api.redoMentorCourseware(
              coursewareId: cid,
              commandId: _nextCmdId('redo'),
              expectedStateRevision: view['state_revision'] as int,
            );
      if (!mounted) return;
      setState(() {
        _view = updated;
        _error = null;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = undo ? '撤销失败，请刷新重试。' : '重做失败，请刷新重试。');
    } finally {
      if (mounted) setState(() => _movingCursor = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final history = _view?['history_controls'] is Map
        ? Map<String, dynamic>.from(_view!['history_controls'] as Map)
        : const <String, dynamic>{};
    final canUndo = history['can_undo'] == true;
    final canRedo = history['can_redo'] == true;
    final cv = _view?['current_version'] is Map
        ? Map<String, dynamic>.from(_view!['current_version'] as Map)
        : null;
    final verNo = cv?['version_no'];

    return Scaffold(
      appBar: AppBar(
        title: Text(verNo != null ? '深度课件 · v$verNo' : '深度课件'),
        actions: [
          IconButton(
            tooltip: '撤销',
            onPressed: canUndo && !_movingCursor
                ? () => _moveCursor(undo: true)
                : null,
            icon: const Icon(Icons.undo),
          ),
          IconButton(
            tooltip: '重做',
            onPressed: canRedo && !_movingCursor
                ? () => _moveCursor(undo: false)
                : null,
            icon: const Icon(Icons.redo),
          ),
          IconButton(
            tooltip: _deckMode ? '切换全览' : '切换分步翻页',
            onPressed: _steps.isEmpty
                ? null
                : () => setState(() => _deckMode = !_deckMode),
            icon: Icon(_deckMode ? Icons.view_agenda_outlined : Icons.slideshow),
          ),
        ],
      ),
      body: Column(
        children: [
          if (_error != null)
            MaterialBanner(
              content: Text(_error!),
              actions: [
                TextButton(onPressed: _refresh, child: const Text('重试')),
              ],
            ),
          Expanded(child: _buildBody(cv)),
          if (cv != null) _buildRevisionBar(),
        ],
      ),
    );
  }

  Widget _buildBody(Map<String, dynamic>? cv) {
    final summary = _view?['verification_summary'] is Map
        ? Map<String, dynamic>.from(_view!['verification_summary'] as Map)
        : null;
    final statusMsg = _status?['message'] as String? ?? '正在生成深度课件...';
    final isDrafting = _view == null || _view?['status'] == 'drafting';
    final revPending = _view?['active_revision_pending'] == true;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (summary != null) _buildSummaryCard(summary, cv),
        if (isDrafting || revPending)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Row(
                  children: [
                    const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        revPending ? '正在按你的要求局部修订（可随时撤销）...' : statusMsg,
                        style: const TextStyle(fontSize: 13),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        if (_view?['status'] == 'failed')
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Card(
              color: const Color(0xfffffbeb),
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Text(
                  (_view?['degraded_text'] as String?) ??
                      '深度课件暂未生成成功，请返回查看常规解析。',
                ),
              ),
            ),
          ),
        if (cv != null) ...[
          const SizedBox(height: 12),
          if (_deckMode)
            _buildDeckStep()
          else
            for (final step in _steps) _buildCollapsibleStep(step),
        ],
      ],
    );
  }

  Widget _buildSummaryCard(
      Map<String, dynamic> summary, Map<String, dynamic>? cv) {
    final vStatus = cv?['verification_status'] as String?;
    final methodology = cv?['methodology_key'] as String?;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  vStatus == 'unverified_custom'
                      ? Icons.edit_note
                      : Icons.verified_outlined,
                  size: 16,
                  color: vStatus == 'unverified_custom'
                      ? const Color(0xffb45309)
                      : const Color(0xff0f766e),
                ),
                const SizedBox(width: 6),
                Text(
                  vStatus == 'unverified_custom'
                      ? '自定义修订草稿（未经引擎核验）'
                      : '核验结论速览',
                  style: const TextStyle(
                      fontSize: 13, fontWeight: FontWeight.w700),
                ),
              ],
            ),
            const SizedBox(height: 8),
            ChatMarkdownBody(text: summary['summary_answer'] as String? ?? ''),
            if (methodology != null && methodology.isNotEmpty) ...[
              const SizedBox(height: 8),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: const Color(0xffe0f2fe),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '核心思路：$methodology',
                  style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: Color(0xff0369a1)),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildDeckStep() {
    if (_steps.isEmpty) return const SizedBox.shrink();
    final step = _steps[_deckIndex];
    return Column(
      children: [
        _buildStepDetailCard(step),
        const SizedBox(height: 12),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            OutlinedButton(
              onPressed: _deckIndex > 0
                  ? () => setState(() => _deckIndex--)
                  : null,
              child: const Text('上一步'),
            ),
            Text('${_deckIndex + 1} / ${_steps.length}'),
            FilledButton(
              onPressed: _deckIndex < _steps.length - 1
                  ? () => setState(() => _deckIndex++)
                  : null,
              child: const Text('下一步'),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildCollapsibleStep(Map<String, dynamic> step) {
    final sid = step['step_id'] as String;
    final expanded = _expandedStepIds.contains(sid);
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Column(
        children: [
          ListTile(
            title: Text(step['title'] as String? ?? sid,
                style: const TextStyle(fontWeight: FontWeight.w600)),
            trailing: Icon(expanded ? Icons.expand_less : Icons.expand_more),
            onTap: () => setState(() {
              if (expanded) {
                _expandedStepIds.remove(sid);
              } else {
                _expandedStepIds.add(sid);
              }
            }),
          ),
          if (expanded)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
              child: _buildStepDetailContent(step),
            ),
        ],
      ),
    );
  }

  Widget _buildStepDetailCard(Map<String, dynamic> step) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(step['title'] as String? ?? '',
                style:
                    const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            const SizedBox(height: 10),
            _buildStepDetailContent(step),
          ],
        ),
      ),
    );
  }

  Widget _buildStepDetailContent(Map<String, dynamic> step) {
    final sid = step['step_id'] as String;
    final why = step['thinking_why'] as String?;
    final action = step['action_what'] as String? ?? '';
    final visual = step['visual_spec'];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (visual is Map)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: MathStageView(
              visualSpec: Map<String, dynamic>.from(visual),
            ),
          ),
        if (why != null && why.trim().isNotEmpty)
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(bottom: 10),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: const Color(0xfffef3c7),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text('思考依据：$why',
                style:
                    const TextStyle(fontSize: 13, color: Color(0xff78350f))),
          ),
        ChatMarkdownBody(text: action),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton.icon(
            onPressed: () => setState(() => _pinnedStepId = sid),
            icon: const Icon(Icons.tune, size: 15),
            label: const Text('微调这一步', style: TextStyle(fontSize: 12)),
          ),
        ),
      ],
    );
  }

  Widget _buildRevisionBar() {
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: Color(0xffe2e8f0))),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (_pinnedStepId != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: InputChip(
                  label: Text('针对步骤 $_pinnedStepId 微调',
                      style: const TextStyle(fontSize: 12)),
                  onDeleted: () => setState(() => _pinnedStepId = null),
                ),
              ),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _revisionInput,
                    decoration: const InputDecoration(
                      hintText: '对话微调课件（如：拆细这步 / 换相似法 / 删掉变式）',
                      isDense: true,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                  tooltip: '提交修订',
                  onPressed: _sendRevision,
                  icon: const Icon(Icons.arrow_upward, size: 18),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
