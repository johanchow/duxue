import 'dart:convert';

/// Deterministic client-side diff between two courseware views (Phase 1).
///
/// Compares `step_id`, `content_hash`, and individual semantic blocks
/// (`visual_spec`, `thinking_why`, `action_what`) without extra API/LLM calls.
class CoursewareRevisionDiff {
  const CoursewareRevisionDiff({
    required this.versionNo,
    required this.summary,
    required this.addedStepIds,
    required this.updatedStepIds,
    required this.visualUpdatedStepIds,
    required this.whyUpdatedStepIds,
    required this.actionUpdatedStepIds,
    required this.deletedStepTitles,
    required this.stepTitleById,
  });

  final int versionNo;
  final String summary;
  final List<String> addedStepIds;
  final List<String> updatedStepIds;
  final Set<String> visualUpdatedStepIds;
  final Set<String> whyUpdatedStepIds;
  final Set<String> actionUpdatedStepIds;
  final List<String> deletedStepTitles;
  final Map<String, String> stepTitleById;

  List<String> get changedOrder => [...addedStepIds, ...updatedStepIds];

  bool get hasAnyChange =>
      addedStepIds.isNotEmpty ||
      updatedStepIds.isNotEmpty ||
      deletedStepTitles.isNotEmpty;

  bool isAdded(String stepId) => addedStepIds.contains(stepId);
  bool isUpdated(String stepId) => updatedStepIds.contains(stepId);
  bool isVisualUpdated(String stepId) => visualUpdatedStepIds.contains(stepId);
  bool isWhyUpdated(String stepId) => whyUpdatedStepIds.contains(stepId);
  bool isActionUpdated(String stepId) => actionUpdatedStepIds.contains(stepId);
}

String _visualSignature(dynamic visual) {
  if (visual is! Map) return '';
  final hash = visual['content_hash'];
  if (hash is String && hash.isNotEmpty) return hash;
  try {
    return jsonEncode(visual);
  } catch (_) {
    return visual.toString();
  }
}

String _stepSignature(Map<String, dynamic> step) {
  final hash = step['content_hash'];
  if (hash is String && hash.isNotEmpty) return hash;
  return [
    step['title'] ?? '',
    step['thinking_why'] ?? '',
    step['action_what'] ?? '',
    _visualSignature(step['visual_spec']),
  ].join('\u001f');
}

CoursewareRevisionDiff? computeCoursewareDiff(
  Map<String, dynamic>? prevView,
  Map<String, dynamic>? nextView,
) {
  final prevCv = prevView?['current_version'];
  final nextCv = nextView?['current_version'];
  if (prevCv is! Map || nextCv is! Map) return null;

  final prevVerNo = prevCv['version_no'];
  final nextVerNo = nextCv['version_no'];
  if (prevVerNo is! int || nextVerNo is! int || prevVerNo == nextVerNo) {
    return null;
  }

  final prevSteps = ((prevCv['steps'] as List?) ?? const [])
      .whereType<Map>()
      .map((e) => Map<String, dynamic>.from(e))
      .toList();
  final nextSteps = ((nextCv['steps'] as List?) ?? const [])
      .whereType<Map>()
      .map((e) => Map<String, dynamic>.from(e))
      .toList();

  final prevById = <String, Map<String, dynamic>>{
    for (final s in prevSteps)
      if (s['step_id'] is String) s['step_id'] as String: s,
  };
  final nextById = <String, Map<String, dynamic>>{
    for (final s in nextSteps)
      if (s['step_id'] is String) s['step_id'] as String: s,
  };

  final addedIds = <String>[];
  final updatedIds = <String>[];
  final visualUpdatedIds = <String>{};
  final whyUpdatedIds = <String>{};
  final actionUpdatedIds = <String>{};
  final deletedTitles = <String>[];
  final titleById = <String, String>{};

  for (final step in nextSteps) {
    final sid = step['step_id'] as String?;
    if (sid == null) continue;
    final title = (step['title'] as String? ?? sid).trim();
    titleById[sid] = title.isEmpty ? sid : title;

    final old = prevById[sid];
    if (old == null) {
      addedIds.add(sid);
      if (step['visual_spec'] is Map) visualUpdatedIds.add(sid);
      continue;
    }

    if (_stepSignature(old) != _stepSignature(step)) {
      updatedIds.add(sid);
      if (_visualSignature(old['visual_spec']) !=
          _visualSignature(step['visual_spec'])) {
        visualUpdatedIds.add(sid);
      }
      if ((old['thinking_why'] as String? ?? '').trim() !=
          (step['thinking_why'] as String? ?? '').trim()) {
        whyUpdatedIds.add(sid);
      }
      if ((old['action_what'] as String? ?? '').trim() !=
              (step['action_what'] as String? ?? '').trim() ||
          (old['title'] as String? ?? '').trim() !=
              (step['title'] as String? ?? '').trim()) {
        actionUpdatedIds.add(sid);
      }
    }
  }

  for (final old in prevSteps) {
    final sid = old['step_id'] as String?;
    if (sid != null && !nextById.containsKey(sid)) {
      final title = (old['title'] as String? ?? sid).trim();
      deletedTitles.add(title.isEmpty ? sid : title);
    }
  }

  final rawSummary = (nextCv['change_summary'] as String? ?? '').trim();
  return CoursewareRevisionDiff(
    versionNo: nextVerNo,
    summary: rawSummary.isNotEmpty ? rawSummary : '课件已更新',
    addedStepIds: addedIds,
    updatedStepIds: updatedIds,
    visualUpdatedStepIds: visualUpdatedIds,
    whyUpdatedStepIds: whyUpdatedIds,
    actionUpdatedStepIds: actionUpdatedIds,
    deletedStepTitles: deletedTitles,
    stepTitleById: titleById,
  );
}
