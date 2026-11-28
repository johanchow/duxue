import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';
import '../../shared/chat_markdown.dart';
import 'courseware_revision_diff.dart';
import 'math_stage_view.dart';

/// Adult MentorCourseware page (P0-1 + Phase 1 Revision Change Awareness):
/// - Responsive layout: single-column on mobile portrait, dual-pane on wide/web landscape
/// - Phase 1 fast verification summary + collapsible outline / deck mode
/// - Interactive MathStageView per step with single-step static fallback
/// - Dialogue-based localized revision with change receipt, auto-expand/scroll,
///   step/block change badges, instruction echo, and failure banner
/// - Millisecond Undo / Redo (allowed even while a revision is in-flight)
class GuardianCoursewarePage extends ConsumerStatefulWidget {
  const GuardianCoursewarePage({
    required this.promptText,
    this.attachmentKeys = const [],
    this.initialCoursewareId,
    this.onCreated,
    this.sourceMessageId,
    super.key,
  });

  final String? sourceMessageId;
  final String promptText;
  final List<String> attachmentKeys;
  final String? initialCoursewareId;
  final ValueChanged<String>? onCreated;

  @override
  ConsumerState<GuardianCoursewarePage> createState() =>
      _GuardianCoursewarePageState();
}

class _RevisionLogEntry {
  const _RevisionLogEntry({
    required this.isUser,
    required this.text,
    this.isError = false,
  });

  final bool isUser;
  final String text;
  final bool isError;
}

class _GuardianCoursewarePageState
    extends ConsumerState<GuardianCoursewarePage> {
  static const double _wideBreakpoint = 860;
  static const Color _bgColor = Color(0xfff8fafc);
  static const Color _borderColor = Color(0xffe2e8f0);
  static const Color _teal = Color(0xff0f766e);
  static const Color _blue = Color(0xff2563eb);
  static const Color _blueSoft = Color(0xffdbeafe);
  static const Color _green = Color(0xff059669);
  static const Color _greenSoft = Color(0xffd1fae5);

  final _revisionInput = TextEditingController();
  final _stepKeys = <String, GlobalKey>{};
  final Set<String> _expandedStepIds = {};
  final List<_RevisionLogEntry> _revisionLog = [];

  Timer? _pollTimer;
  Timer? _flashTimer;
  String? _coursewareId;
  Map<String, dynamic>? _view;
  Map<String, dynamic>? _preRevisionView;
  Map<String, dynamic>? _status;
  String? _error;
  String? _pendingInstruction;
  String? _revisionFailureMessage;
  String? _failedInstruction;
  String? _handledFailedRevisionId;
  CoursewareRevisionDiff? _activeDiff;
  String? _flashStepId;
  int _focusChangeIdx = 0;
  bool _deckMode = false;
  int _deckIndex = 0;
  int _cmdSeq = 0;
  bool _movingCursor = false;
  bool _saving = false;
  bool _allowLeave = false;
  Future<List<String>>? _photos;

  String _nextCmdId(String prefix) =>
      '$prefix-${DateTime.now().microsecondsSinceEpoch}-${++_cmdSeq}';

  GlobalKey _keyForStep(String stepId) =>
      _stepKeys.putIfAbsent(stepId, () => GlobalKey());

  @override
  void initState() {
    super.initState();
    _coursewareId = widget.initialCoursewareId;
    unawaited(_bootstrap());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _flashTimer?.cancel();
    _revisionInput.dispose();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    try {
      final api = ref.read(apiProvider);
      if (_coursewareId == null) {
        final created = await api.createMentorCourseware(
          commandId: widget.sourceMessageId == null ? _nextCmdId('create') : 'turn-${widget.sourceMessageId}',
          promptText: widget.promptText,
          attachmentKeys: widget.attachmentKeys,
        );
        if (!mounted) return;
        _coursewareId = created['courseware_id'] as String?;
        if (_coursewareId != null) widget.onCreated?.call(_coursewareId!);
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

  void _triggerFlash(String? stepId) {
    _flashTimer?.cancel();
    _flashStepId = stepId;
    if (stepId == null) return;
    _flashTimer = Timer(const Duration(milliseconds: 1400), () {
      if (!mounted) return;
      setState(() => _flashStepId = null);
    });
  }

  void _scrollToStep(String stepId) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final ctx = _stepKeys[stepId]?.currentContext;
      if (ctx != null) {
        Scrollable.ensureVisible(
          ctx,
          duration: const Duration(milliseconds: 280),
          curve: Curves.easeOut,
          alignment: 0.22,
        );
      }
    });
  }

  Future<void> _refresh() async {
    final cid = _coursewareId;
    if (cid == null) return;
    try {
      final api = ref.read(apiProvider);
      final view = await api.getMentorCourseware(cid);
      final status = await api.getMentorCoursewareStatus(cid);
      if (!mounted) return;

      final prevView = _preRevisionView ?? _view;
      final prevVer = (prevView?['current_version'] as Map?)?['version_no'];
      final nextVer = (view['current_version'] as Map?)?['version_no'];
      final revPending = view['active_revision_pending'] == true;
      final statusStage = status['stage'] as String?;
      final statusRevId = status['revision_id'] as String?;

      CoursewareRevisionDiff? newDiff;
      String? autoScrollTarget;
      String? failureMsg;

      if (!revPending &&
          prevVer is int &&
          nextVer is int &&
          nextVer != prevVer) {
        newDiff = computeCoursewareDiff(prevView, view);
      } else if (!revPending &&
          view['status'] == 'ready' &&
          statusStage == 'failed' &&
          (_pendingInstruction != null ||
              (statusRevId != null &&
                  statusRevId != _handledFailedRevisionId))) {
        failureMsg = (status['message'] as String? ?? '').trim();
        if (failureMsg.isEmpty) failureMsg = '修订未生效，原版本保持不变。';
        _handledFailedRevisionId = statusRevId;
      }

      setState(() {
        _view = view;
        _status = status;
        _error = null;

        final steps = _steps;
        if (steps.isNotEmpty && _expandedStepIds.isEmpty) {
          _expandedStepIds.add(steps.first['step_id'] as String);
        }

        if (newDiff != null) {
          _activeDiff = newDiff;
          _focusChangeIdx = 0;
          _preRevisionView = null;
          _pendingInstruction = null;
          _revisionFailureMessage = null;
          _failedInstruction = null;
          _revisionLog.add(_RevisionLogEntry(
            isUser: false,
            text: '已更新至 v${newDiff.versionNo}：${newDiff.summary}',
          ));
          for (final sid in newDiff.changedOrder) {
            _expandedStepIds.add(sid);
          }
          if (newDiff.changedOrder.isNotEmpty) {
            final firstSid = newDiff.changedOrder.first;
            _triggerFlash(firstSid);
            if (_deckMode) {
              final idx = steps.indexWhere((s) => s['step_id'] == firstSid);
              if (idx >= 0) _deckIndex = idx;
            } else {
              autoScrollTarget = firstSid;
            }
          }
        } else if (failureMsg != null) {
          _revisionFailureMessage = failureMsg;
          _failedInstruction = _pendingInstruction;
          _pendingInstruction = null;
          _preRevisionView = null;
          _revisionLog.add(_RevisionLogEntry(
            isUser: false,
            text: '修订未生效：$failureMsg',
            isError: true,
          ));
        }

        if (_deckIndex >= steps.length && steps.isNotEmpty) {
          _deckIndex = steps.length - 1;
        }
      });

      if (autoScrollTarget != null) {
        _scrollToStep(autoScrollTarget!);
      }

      if (view['status'] != 'drafting' && !revPending) {
        _pollTimer?.cancel();
      }
    } catch (error) {
      if (!mounted) return;
      if (error is DioException && error.response?.statusCode == 404) {
        _pollTimer?.cancel();
        setState(() {
          _view = null;
          _coursewareId = null;
          _error = '课件已过期或已删除。';
        });
      } else {
        setState(() => _error = '读取课件状态失败，请点击重试。');
      }
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
    setState(() {
      _preRevisionView = view;
      _pendingInstruction = text;
      _revisionFailureMessage = null;
      _failedInstruction = null;
      _revisionLog.add(_RevisionLogEntry(isUser: true, text: text));
    });

    try {
      final api = ref.read(apiProvider);
      await api.requestMentorCoursewareRevision(
        coursewareId: cid,
        commandId: _nextCmdId('rev'),
        instruction: text,
        baseVersionNo: cv['version_no'] as int,
        expectedStateRevision: view['state_revision'] as int,
      );
      if (!mounted) return;
      await _refresh();
      _ensurePolling();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _pendingInstruction = null;
        _preRevisionView = null;
        _revisionFailureMessage = '提交修订失败，请稍后重试。';
        _failedInstruction = text;
        _revisionLog.add(const _RevisionLogEntry(
          isUser: false,
          text: '提交修订失败，请稍后重试。',
          isError: true,
        ));
      });
    }
  }

  void _jumpToNextChange() {
    final diff = _activeDiff;
    if (diff == null || diff.changedOrder.isEmpty) return;
    final sid = diff.changedOrder[_focusChangeIdx % diff.changedOrder.length];
    _focusChangeIdx = (_focusChangeIdx + 1) % diff.changedOrder.length;
    setState(() {
      _expandedStepIds.add(sid);
      _triggerFlash(sid);
      if (_deckMode) {
        final idx = _steps.indexWhere((s) => s['step_id'] == sid);
        if (idx >= 0) _deckIndex = idx;
      }
    });
    if (!_deckMode) _scrollToStep(sid);
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
        _activeDiff = null;
        _flashStepId = null;
        _pendingInstruction = null;
        _preRevisionView = null;
        final steps = _steps;
        if (_deckIndex >= steps.length && steps.isNotEmpty) {
          _deckIndex = steps.length - 1;
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = undo ? '撤销失败，请刷新重试。' : '重做失败，请刷新重试。');
    } finally {
      if (mounted) setState(() => _movingCursor = false);
    }
  }

  Future<bool> _save() async {
    if (_saving || _coursewareId == null) return false;
    setState(() => _saving = true);
    try {
      await ref.read(apiProvider).changeSavedCourseware(
          _coursewareId!, 'save', _view!['state_revision'] as int);
      await _refresh();
      return _view?['retention_status'] == 'saved';
    } catch (_) {
      if (mounted) setState(() => _error = '保存失败，请刷新后重试。');
      return false;
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _leave() async {
    final save = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
                title: const Text('保存这份课件？'),
                content: const Text('保存后可以在「我的资源库」继续查看和修改。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(ctx, false),
                      child: const Text('直接离开')),
                  FilledButton(
                      onPressed: () => Navigator.pop(ctx, true),
                      child: const Text('保存并离开'))
                ]));
    if (save == null || (save && !await _save()) || !mounted) return;
    setState(() => _allowLeave = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) Navigator.pop(context);
    });
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
    final temporary = _view?['retention_status'] == 'temporary' && cv != null;

    return PopScope(
      canPop: !temporary || _allowLeave,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && !_saving) unawaited(_leave());
      },
      child: Scaffold(
        backgroundColor: _bgColor,
        appBar: AppBar(
          backgroundColor: Colors.white,
          surfaceTintColor: Colors.white,
          elevation: 0,
          bottom: const PreferredSize(
            preferredSize: Size.fromHeight(1),
            child: Divider(height: 1, color: _borderColor),
          ),
          title: Text(
            verNo != null ? '深度课件 · v$verNo' : '深度课件',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
          ),
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
              icon: Icon(
                  _deckMode ? Icons.view_agenda_outlined : Icons.slideshow),
            ),
          ],
        ),
        body: LayoutBuilder(
          builder: (context, constraints) {
            final isWide = constraints.maxWidth >= _wideBreakpoint;
            if (isWide) {
              return _buildWideLayout(
                cv: cv,
                temporary: temporary,
                canUndo: canUndo,
                verNo: verNo as int?,
              );
            }
            return _buildCompactLayout(
              cv: cv,
              temporary: temporary,
              canUndo: canUndo,
            );
          },
        ),
      ),
    );
  }

  Widget _buildCompactLayout({
    required Map<String, dynamic>? cv,
    required bool temporary,
    required bool canUndo,
  }) {
    return Column(
      children: [
        if (_error != null) _buildErrorBanner(),
        if (temporary) _buildTemporaryRetentionBar(),
        Expanded(child: _buildBody(cv, showInlineRevisionStatus: true)),
        if (cv != null && _activeDiff != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
            child: _buildRevisionReceiptBanner(_activeDiff!, canUndo: canUndo),
          ),
        if (cv != null) _buildRevisionBar(),
      ],
    );
  }

  Widget _buildWideLayout({
    required Map<String, dynamic>? cv,
    required bool temporary,
    required bool canUndo,
    required int? verNo,
  }) {
    return Row(
      key: const ValueKey('courseware-wide-layout'),
      children: [
        Expanded(
          child: Column(
            children: [
              if (_error != null) _buildErrorBanner(),
              if (temporary) _buildTemporaryRetentionBar(),
              Expanded(
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 820),
                    child: _buildBody(cv, showInlineRevisionStatus: false),
                  ),
                ),
              ),
            ],
          ),
        ),
        if (cv != null)
          Container(
            key: const ValueKey('courseware-wide-sidebar'),
            width: 360,
            decoration: const BoxDecoration(
              color: _bgColor,
              border: Border(left: BorderSide(color: _borderColor)),
            ),
            child: Column(
              children: [
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  decoration: const BoxDecoration(
                    color: Colors.white,
                    border: Border(bottom: BorderSide(color: _borderColor)),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        '课件修订',
                        style: TextStyle(
                            fontSize: 13.5, fontWeight: FontWeight.w700),
                      ),
                      if (verNo != null)
                        Text(
                          '当前 v$verNo',
                          style: const TextStyle(
                              fontSize: 12, color: Color(0xff64748b)),
                        ),
                    ],
                  ),
                ),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.all(12),
                    children: [
                      if (_activeDiff != null) ...[
                        _buildRevisionReceiptBanner(_activeDiff!,
                            canUndo: canUndo),
                        const SizedBox(height: 12),
                      ],
                      if (_view?['active_revision_pending'] == true ||
                          _pendingInstruction != null) ...[
                        _buildPendingCard(isRevision: true),
                        const SizedBox(height: 12),
                      ],
                      if (_revisionFailureMessage != null) ...[
                        _buildRevisionFailureBanner(),
                        const SizedBox(height: 12),
                      ],
                      const Padding(
                        padding: EdgeInsets.only(bottom: 8),
                        child: Text(
                          '本轮修订记录',
                          style: TextStyle(
                            fontSize: 11.5,
                            fontWeight: FontWeight.w700,
                            color: Color(0xff64748b),
                          ),
                        ),
                      ),
                      if (_revisionLog.isEmpty)
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: _borderColor),
                          ),
                          child: const Text(
                            '直接在下方输入修改要求（如：把第 2 步讲细一点、补充生活类比或删掉某一步），生效后会在此标明改动位置。',
                            style: TextStyle(
                              fontSize: 12.5,
                              height: 1.5,
                              color: Color(0xff475569),
                            ),
                          ),
                        )
                      else
                        for (final entry in _revisionLog)
                          _buildLogBubble(entry),
                    ],
                  ),
                ),
                _buildRevisionBar(),
              ],
            ),
          ),
      ],
    );
  }

  Widget _buildLogBubble(_RevisionLogEntry entry) {
    final bg = entry.isUser
        ? _teal
        : (entry.isError ? const Color(0xfffee2e2) : Colors.white);
    final fg = entry.isUser
        ? Colors.white
        : (entry.isError ? const Color(0xff991b1b) : const Color(0xff0f172a));
    final borderColor = entry.isUser
        ? Colors.transparent
        : (entry.isError ? const Color(0xfffecaca) : _borderColor);

    return Align(
      alignment: entry.isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
        constraints: const BoxConstraints(maxWidth: 300),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: borderColor),
        ),
        child: Text(
          entry.text,
          style: TextStyle(fontSize: 12.5, height: 1.45, color: fg),
        ),
      ),
    );
  }

  Widget _buildErrorBanner() {
    return MaterialBanner(
      content: Text(_error!),
      actions: [
        if (_coursewareId != null || widget.promptText.isNotEmpty)
          TextButton(
            onPressed: _coursewareId == null ? _bootstrap : _refresh,
            child: Text(_coursewareId == null ? '重新生成' : '重试'),
          ),
      ],
    );
  }

  Widget _buildTemporaryRetentionBar() {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: _borderColor)),
      ),
      child: ListTile(
        dense: true,
        visualDensity: VisualDensity.compact,
        title: const Text(
          '临时课件 · 4 小时有效',
          style: TextStyle(fontSize: 13, color: Color(0xff475569)),
        ),
        trailing: TextButton(
          onPressed: _saving || _view?['active_revision_pending'] == true
              ? null
              : _save,
          child: Text(_saving ? '保存中…' : '保存课件'),
        ),
      ),
    );
  }

  Widget _buildBody(
    Map<String, dynamic>? cv, {
    required bool showInlineRevisionStatus,
  }) {
    final summary = _view?['verification_summary'] is Map
        ? Map<String, dynamic>.from(_view!['verification_summary'] as Map)
        : null;
    final isDrafting = _view == null || _view?['status'] == 'drafting';
    final revPending =
        _view?['active_revision_pending'] == true || _pendingInstruction != null;
    final stem = (summary?['stem_text'] as String? ?? '').trim();

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (stem.isNotEmpty) ...[
          const Text(
            '题目',
            style: TextStyle(
              fontSize: 12.5,
              fontWeight: FontWeight.w700,
              color: Color(0xff64748b),
            ),
          ),
          const SizedBox(height: 6),
          ChatMarkdownBody(text: stem),
          const SizedBox(height: 12),
        ],
        if (_view?['retention_status'] == 'saved')
          FutureBuilder<List<String>>(
            future: _photos ??=
                ref.read(apiProvider).savedCoursewarePhotos(_coursewareId!),
            builder: (_, snapshot) => Column(
              children: [
                for (final photo in snapshot.data ?? <String>[])
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(10),
                      child: Image.memory(base64Decode(photo), height: 160),
                    ),
                  ),
              ],
            ),
          ),
        if (summary != null) _buildSummaryCard(summary, cv),
        if (isDrafting)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: _buildPendingCard(isRevision: false),
          ),
        if (!isDrafting && revPending && showInlineRevisionStatus)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: _buildPendingCard(isRevision: true),
          ),
        if (showInlineRevisionStatus && _revisionFailureMessage != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: _buildRevisionFailureBanner(),
          ),
        if (_view?['status'] == 'failed')
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xfffffbeb),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xfffde68a)),
              ),
              child: Text(
                (_view?['degraded_text'] as String?) ??
                    '深度课件暂未生成成功，请返回查看常规解析。',
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

  Widget _buildPendingCard({required bool isRevision}) {
    final statusMsg = _status?['message'] as String? ?? '正在生成深度课件...';
    final text = isRevision
        ? (_pendingInstruction != null
            ? '正在处理：“$_pendingInstruction”...'
            : '正在按你的要求局部修订（可随时撤销）...')
        : statusMsg;
    return Container(
      key: ValueKey(isRevision ? 'revision-pending-card' : 'drafting-card'),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: const Color(0xffeff6ff),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xffbfdbfe)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(top: 2),
            child: SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2, color: _blue),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                fontSize: 13,
                color: Color(0xff1e3a8a),
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRevisionFailureBanner() {
    return Container(
      key: const ValueKey('revision-failure-banner'),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xfffee2e2),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xfffecaca)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, size: 18, color: Color(0xffb91c1c)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              _revisionFailureMessage!,
              style: const TextStyle(
                fontSize: 12.5,
                color: Color(0xff991b1b),
                height: 1.4,
              ),
            ),
          ),
          if (_failedInstruction != null)
            TextButton(
              style: TextButton.styleFrom(
                visualDensity: VisualDensity.compact,
                foregroundColor: const Color(0xffb91c1c),
              ),
              onPressed: () {
                _revisionInput.text = _failedInstruction!;
                setState(() {
                  _revisionFailureMessage = null;
                  _failedInstruction = null;
                });
              },
              child: const Text('回填'),
            ),
          IconButton(
            visualDensity: VisualDensity.compact,
            tooltip: '关闭失败提示',
            onPressed: () => setState(() {
              _revisionFailureMessage = null;
              _failedInstruction = null;
            }),
            icon: const Icon(Icons.close, size: 16, color: Color(0xff991b1b)),
          ),
        ],
      ),
    );
  }

  Widget _buildRevisionReceiptBanner(
    CoursewareRevisionDiff diff, {
    required bool canUndo,
  }) {
    String shortTitle(String raw) => raw.split('：').first.trim();

    return Container(
      key: const ValueKey('revision-receipt-banner'),
      padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
      decoration: BoxDecoration(
        color: const Color(0xfff0fdf4),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xff86efac)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x14059669),
            blurRadius: 8,
            offset: Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.only(top: 1),
                child: Icon(Icons.check_circle, size: 16, color: _green),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  '已更新至 v${diff.versionNo} · ${diff.summary}',
                  style: const TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: Color(0xff14532d),
                    height: 1.35,
                  ),
                ),
              ),
              InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () => setState(() {
                  _activeDiff = null;
                  _flashStepId = null;
                }),
                child: const Padding(
                  padding: EdgeInsets.all(2),
                  child: Icon(Icons.close, size: 16, color: Color(0xff15803d)),
                ),
              ),
            ],
          ),
          if (diff.hasAnyChange) ...[
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                for (final sid in diff.addedStepIds)
                  _buildDiffChip(
                    label: '+ 新增：${shortTitle(diff.stepTitleById[sid] ?? sid)}',
                    bg: _greenSoft,
                    fg: const Color(0xff047857),
                  ),
                for (final sid in diff.updatedStepIds)
                  _buildDiffChip(
                    label:
                        '已更新：${shortTitle(diff.stepTitleById[sid] ?? sid)}${diff.isVisualUpdated(sid) ? '（含图示）' : ''}',
                    bg: _blueSoft,
                    fg: const Color(0xff1d4ed8),
                  ),
                for (final title in diff.deletedStepTitles)
                  _buildDiffChip(
                    label: '已移除：${shortTitle(title)}',
                    bg: const Color(0xfffee2e2),
                    fg: const Color(0xffb91c1c),
                    strike: true,
                  ),
              ],
            ),
          ],
          if (diff.changedOrder.isNotEmpty || canUndo) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                if (diff.changedOrder.isNotEmpty)
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      visualDensity: VisualDensity.compact,
                      backgroundColor: Colors.white,
                      foregroundColor: const Color(0xff15803d),
                      side: const BorderSide(color: Color(0xff86efac)),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 4),
                      textStyle: const TextStyle(
                          fontSize: 12, fontWeight: FontWeight.w600),
                    ),
                    onPressed: _jumpToNextChange,
                    icon: const Icon(Icons.my_location, size: 14),
                    label: const Text('定位到改动处'),
                  ),
                if (canUndo)
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      visualDensity: VisualDensity.compact,
                      backgroundColor: Colors.white,
                      foregroundColor: const Color(0xff334155),
                      side: const BorderSide(color: Color(0xffcbd5e1)),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 4),
                      textStyle: const TextStyle(
                          fontSize: 12, fontWeight: FontWeight.w600),
                    ),
                    onPressed:
                        _movingCursor ? null : () => _moveCursor(undo: true),
                    icon: const Icon(Icons.undo, size: 14),
                    label: const Text('撤销本次修改'),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildDiffChip({
    required String label,
    required Color bg,
    required Color fg,
    bool strike = false,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: fg,
          decoration: strike ? TextDecoration.lineThrough : null,
        ),
      ),
    );
  }

  Widget _buildSummaryCard(
    Map<String, dynamic> summary,
    Map<String, dynamic>? cv,
  ) {
    final vStatus = cv?['verification_status'] as String?;
    final methodology = cv?['methodology_key'] as String?;
    final isCustom = vStatus == 'unverified_custom';
    final isLow = vStatus == 'low_confidence';
    final badgeColor =
        (isCustom || isLow) ? const Color(0xffb45309) : _teal;
    final badgeIcon = isCustom
        ? Icons.edit_note
        : (isLow ? Icons.info_outline : Icons.verified_outlined);
    final badgeText = isCustom
        ? '自定义修订草稿（未经引擎核验）'
        : (isLow ? '参考结论（核验置信度较低）' : '核验结论速览');

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _borderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(badgeIcon, size: 16, color: badgeColor),
              const SizedBox(width: 6),
              Text(
                badgeText,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: badgeColor,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ChatMarkdownBody(text: summary['summary_answer'] as String? ?? ''),
          if (methodology != null && methodology.isNotEmpty) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0xffe0f2fe),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                '核心思路：$methodology',
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: Color(0xff0369a1),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildDeckStep() {
    if (_steps.isEmpty) return const SizedBox.shrink();
    final step = _steps[_deckIndex];
    final diff = _activeDiff;
    return Column(
      children: [
        _buildStepDetailCard(step),
        const SizedBox(height: 12),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            OutlinedButton(
              onPressed:
                  _deckIndex > 0 ? () => setState(() => _deckIndex--) : null,
              child: const Text('上一步'),
            ),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (var i = 0; i < _steps.length; i++) ...[
                  Builder(builder: (_) {
                    final sid = _steps[i]['step_id'] as String;
                    final changed = diff != null &&
                        (diff.isAdded(sid) || diff.isUpdated(sid));
                    final isCurrent = i == _deckIndex;
                    return Container(
                      width: isCurrent ? 9 : 7,
                      height: isCurrent ? 9 : 7,
                      margin: const EdgeInsets.symmetric(horizontal: 3),
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: changed
                            ? _blue
                            : (isCurrent
                                ? const Color(0xff0f172a)
                                : const Color(0xffcbd5e1)),
                      ),
                    );
                  }),
                ],
                const SizedBox(width: 6),
                Text(
                  '${_deckIndex + 1} / ${_steps.length}',
                  style:
                      const TextStyle(fontSize: 12.5, color: Color(0xff64748b)),
                ),
              ],
            ),
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

  Widget _buildStepBadge(String stepId) {
    final diff = _activeDiff;
    if (diff == null) return const SizedBox.shrink();
    if (diff.isAdded(stepId)) {
      return _buildDiffChip(
        label: '新增',
        bg: _greenSoft,
        fg: const Color(0xff047857),
      );
    }
    if (diff.isUpdated(stepId)) {
      return _buildDiffChip(
        label: diff.isVisualUpdated(stepId) ? '图文已更新' : '已更新',
        bg: _blueSoft,
        fg: const Color(0xff1d4ed8),
      );
    }
    return const SizedBox.shrink();
  }

  BoxDecoration _stepCardDecoration(String stepId) {
    final diff = _activeDiff;
    final isAdded = diff != null && diff.isAdded(stepId);
    final isUpdated = diff != null && diff.isUpdated(stepId);
    final isFlashing = _flashStepId == stepId;

    final borderColor = isAdded
        ? const Color(0xff6ee7b7)
        : (isUpdated ? const Color(0xff93c5fd) : _borderColor);
    final bgColor = isFlashing ? const Color(0xffeff6ff) : Colors.white;

    return BoxDecoration(
      color: bgColor,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: borderColor),
      boxShadow: isFlashing
          ? const [
              BoxShadow(
                color: Color(0x332563eb),
                blurRadius: 8,
                spreadRadius: 1,
              ),
            ]
          : null,
    );
  }

  Widget _wrapStepAccentBar({required String stepId, required Widget child}) {
    final diff = _activeDiff;
    final isAdded = diff != null && diff.isAdded(stepId);
    final isUpdated = diff != null && diff.isUpdated(stepId);
    if (!isAdded && !isUpdated) return child;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: Container(
        decoration: BoxDecoration(
          border: Border(
            left: BorderSide(
              color: isAdded ? _green : _blue,
              width: 4,
            ),
          ),
        ),
        child: child,
      ),
    );
  }

  Widget _buildCollapsibleStep(Map<String, dynamic> step) {
    final sid = step['step_id'] as String;
    final expanded = _expandedStepIds.contains(sid);
    return AnimatedContainer(
      key: _keyForStep(sid),
      duration: const Duration(milliseconds: 280),
      margin: const EdgeInsets.only(bottom: 10),
      decoration: _stepCardDecoration(sid),
      child: _wrapStepAccentBar(
        stepId: sid,
        child: Column(
          children: [
            InkWell(
              borderRadius: BorderRadius.circular(12),
              onTap: () => setState(() {
                if (expanded) {
                  _expandedStepIds.remove(sid);
                } else {
                  _expandedStepIds.add(sid);
                }
              }),
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        step['title'] as String? ?? sid,
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    _buildStepBadge(sid),
                    const SizedBox(width: 4),
                    Icon(
                      expanded ? Icons.expand_less : Icons.expand_more,
                      color: const Color(0xff64748b),
                    ),
                  ],
                ),
              ),
            ),
            if (expanded)
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                child: _buildStepDetailContent(step),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildStepDetailCard(Map<String, dynamic> step) {
    final sid = step['step_id'] as String;
    return AnimatedContainer(
      key: _keyForStep(sid),
      duration: const Duration(milliseconds: 280),
      decoration: _stepCardDecoration(sid),
      child: _wrapStepAccentBar(
        stepId: sid,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      step['title'] as String? ?? '',
                      style: const TextStyle(
                          fontSize: 15.5, fontWeight: FontWeight.w700),
                    ),
                  ),
                  const SizedBox(width: 8),
                  _buildStepBadge(sid),
                ],
              ),
              const SizedBox(height: 10),
              _buildStepDetailContent(step),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBlockTag(String label, {Color color = _blue}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 10.5,
          fontWeight: FontWeight.w700,
          color: Colors.white,
        ),
      ),
    );
  }

  Widget _buildStepDetailContent(Map<String, dynamic> step) {
    final sid = step['step_id'] as String;
    final why = step['thinking_why'] as String?;
    final action = step['action_what'] as String? ?? '';
    final visual = step['visual_spec'];
    final diff = _activeDiff;
    final visUpdated = diff != null && diff.isVisualUpdated(sid);
    final whyUpdated = diff != null && diff.isWhyUpdated(sid);
    final actUpdated = diff != null && diff.isActionUpdated(sid);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (visual is Map)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Stack(
              children: [
                Container(
                  decoration: visUpdated
                      ? BoxDecoration(
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: const Color(0xff38bdf8),
                            width: 1.5,
                          ),
                        )
                      : null,
                  child: MathStageView(
                    visualSpec: Map<String, dynamic>.from(visual),
                  ),
                ),
                if (visUpdated)
                  Positioned(
                    top: 8,
                    right: 8,
                    child: _buildBlockTag('图示已更新', color: const Color(0xff0284c7)),
                  ),
              ],
            ),
          ),
        if (why != null && why.trim().isNotEmpty)
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(bottom: 10),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: const Color(0xfffef3c7),
              borderRadius: BorderRadius.circular(9),
              border: whyUpdated
                  ? Border.all(color: const Color(0xfff59e0b), width: 1.5)
                  : null,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (whyUpdated)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: _buildBlockTag(
                      '思考依据已补充',
                      color: const Color(0xffd97706),
                    ),
                  ),
                Text(
                  '思考依据：$why',
                  style: const TextStyle(
                    fontSize: 13,
                    color: Color(0xff78350f),
                    height: 1.5,
                  ),
                ),
              ],
            ),
          ),
        Container(
          width: double.infinity,
          padding: actUpdated
              ? const EdgeInsets.symmetric(horizontal: 10, vertical: 8)
              : EdgeInsets.zero,
          decoration: actUpdated
              ? BoxDecoration(
                  color: _bgColor,
                  borderRadius: BorderRadius.circular(9),
                  border: Border.all(color: const Color(0xff93c5fd), width: 1.2),
                )
              : null,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (actUpdated)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: _buildBlockTag('讲解已更新'),
                ),
              ChatMarkdownBody(text: action),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildRevisionBar() {
    final busy =
        _view?['active_revision_pending'] == true || _pendingInstruction != null;
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
        decoration: const BoxDecoration(
          color: Colors.white,
          border: Border(top: BorderSide(color: _borderColor)),
        ),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _revisionInput,
                enabled: !busy,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _sendRevision(),
                decoration: InputDecoration(
                  hintText: '想怎样修改课件？',
                  isDense: true,
                  filled: true,
                  fillColor: _bgColor,
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: Color(0xffcbd5e1)),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: Color(0xffcbd5e1)),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                    borderSide: const BorderSide(color: _blue, width: 1.5),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              style: IconButton.styleFrom(
                backgroundColor: _teal,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              tooltip: '提交修订',
              onPressed: busy ? null : _sendRevision,
              icon: const Icon(Icons.arrow_upward, size: 18),
            ),
          ],
        ),
      ),
    );
  }
}
