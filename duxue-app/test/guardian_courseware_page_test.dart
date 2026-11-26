import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/features/guardian_courseware/guardian_courseware_page.dart';
import 'package:duxue_app/features/guardian_courseware/math_stage_view.dart';
import 'package:duxue_app/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _FakeCoursewareApi extends ApiClient {
  _FakeCoursewareApi()
      : super(baseUrl: 'http://localhost', tokens: const TokenStorage());

  int _version = 1;
  int _stateRev = 2;
  int revisionCalls = 0;
  int undoCalls = 0;
  int redoCalls = 0;

  Map<String, dynamic> _buildView() => {
        'courseware_id': 'cw-1',
        'status': 'ready',
        'state_revision': _stateRev,
        'verification_summary': {
          'baseline_hash': 'bh-1',
          'confidence': 'high',
          'summary_answer': '最短路径为 √5',
        },
        'current_version': {
          'version_no': _version,
          'baseline_hash': 'bh-1',
          'change_summary': _version == 1 ? '初版' : '局部修订',
          'verification_status': 'verified',
          'methodology_key': '空间展开降维',
          'steps': [
            {
              'step_id': 's1',
              'title': '展开正方体相邻面',
              'thinking_why': '立体表面折线展开后变成平面线段',
              'action_what': _version == 1
                  ? '将正方体侧面展平，构造长 2 宽 1 的矩形。'
                  : '（已修订）用纸盒展开的例子理解长 2 宽 1 的矩形。',
              'visual_spec': {
                'kind': 'component_scene',
                'title': '正方体 3D 展开',
                'static_fallback_text': '正方体展开为 2×1 矩形',
                'payload': {'component': 'solid_geometry_3d', 'shape': 'cube'},
              },
            },
          ],
        },
        'history_controls': {
          'cursor': _version - 1,
          'total_versions': _version == 1 && revisionCalls == 0 ? 1 : 2,
          'can_undo': _version > 1,
          'can_redo': _version == 1 && revisionCalls > 0,
        },
        'active_revision_pending': false,
      };

  @override
  Future<Map<String, dynamic>> createMentorCourseware({
    required String commandId,
    required String promptText,
    List<String> attachmentKeys = const [],
    String? targetGradeHint,
  }) async =>
      {'courseware_id': 'cw-1', 'status': 'ready', 'state_revision': _stateRev};

  @override
  Future<Map<String, dynamic>> getMentorCourseware(String coursewareId) async =>
      _buildView();

  @override
  Future<Map<String, dynamic>> getMentorCoursewareStatus(
          String coursewareId) async =>
      {'courseware_id': coursewareId, 'stage': 'ready', 'message': '已就绪'};

  @override
  Future<Map<String, dynamic>> requestMentorCoursewareRevision({
    required String coursewareId,
    required String commandId,
    required String instruction,
    required int baseVersionNo,
    required int expectedStateRevision,
    String? targetStepId,
    bool allowUnverifiedOverride = false,
  }) async {
    revisionCalls++;
    _version = 2;
    _stateRev += 2;
    return {
      'courseware_id': coursewareId,
      'revision_id': 'rev-1',
      'base_version_no': baseVersionNo,
      'state_revision': _stateRev,
    };
  }

  @override
  Future<Map<String, dynamic>> undoMentorCourseware({
    required String coursewareId,
    required String commandId,
    required int expectedStateRevision,
  }) async {
    undoCalls++;
    _version = 1;
    _stateRev++;
    return _buildView();
  }

  @override
  Future<Map<String, dynamic>> redoMentorCourseware({
    required String coursewareId,
    required String commandId,
    required int expectedStateRevision,
  }) async {
    redoCalls++;
    _version = 2;
    _stateRev++;
    return _buildView();
  }
}

void main() {
  testWidgets('MentorCoursewarePage renders 3D stage, localized revision, and Undo/Redo',
      (tester) async {
    final api = _FakeCoursewareApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(
          home: GuardianCoursewarePage(promptText: '正方体表面最短路径'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('深度课件 · v1'), findsOneWidget);
    expect(find.text('核心思路：空间展开降维'), findsOneWidget);
    expect(find.text('单指拖转 3D 立体模型'), findsOneWidget);

    // Pin step s1 and send localized revision
    await tester.ensureVisible(find.text('微调这一步'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('微调这一步'));
    await tester.pump();
    expect(find.text('针对步骤 s1 微调'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '补充纸盒展开比喻');
    await tester.tap(find.byTooltip('提交修订'));
    await tester.pumpAndSettle();

    expect(api.revisionCalls, 1);
    expect(find.text('深度课件 · v2'), findsOneWidget);

    // Undo -> v1, Redo -> v2
    await tester.tap(find.byTooltip('撤销'));
    await tester.pumpAndSettle();
    expect(api.undoCalls, 1);
    expect(find.text('深度课件 · v1'), findsOneWidget);

    await tester.tap(find.byTooltip('重做'));
    await tester.pumpAndSettle();
    expect(api.redoCalls, 1);
    expect(find.text('深度课件 · v2'), findsOneWidget);
  });

  testWidgets('MathStageView degrades cleanly to static fallback on stage error',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: MathStageView(
            simulateError: true,
            visualSpec: {
              'kind': 'component_scene',
              'title': '正方体展开',
              'static_fallback_text': '正方体展开为长 2 宽 1 矩形',
              'payload': {'component': 'solid_geometry_3d', 'shape': 'cube'},
            },
          ),
        ),
      ),
    );
    expect(find.byKey(const ValueKey('math-stage-static-fallback')),
        findsOneWidget);
    expect(find.text('正方体展开为长 2 宽 1 矩形'), findsOneWidget);
  });
}
