import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/features/guardian_courseware/courseware_revision_diff.dart';
import 'package:duxue_app/features/guardian_courseware/guardian_courseware_page.dart';
import 'package:duxue_app/features/guardian_courseware/math_stage_view.dart';
import 'package:duxue_app/features/guardian_courseware/library_page.dart';
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

  bool saved = false;
  int creations = 0;
  @override
  Future<void> changeSavedCourseware(String id, String action, int revision,
      {String? title}) async {
    saved = true;
  }

  @override
  Future<List<String>> savedCoursewarePhotos(String id) async => [];
  @override
  Future<Map<String, dynamic>> listSavedCourseware([String? cursor, String? type]) async => {
        'items': [
          if (saved)
            {
              'title': '几何备课',
              'question_text': '棱长为一的正方体，沿表面怎样到达相对顶点？',
              'updated_at': '2026-11-27T10:00:00',
              'courseware_id': 'cw-1',
              'state_revision': 2
            }
        ],
      };
  Map<String, dynamic> _buildView() => {
        'courseware_id': 'cw-1',
        'retention_status': saved ? 'saved' : 'temporary',
        'status': 'ready',
        'state_revision': _stateRev,
        'verification_summary': {
          'baseline_hash': 'bh-1',
          'confidence': 'high',
          'summary_answer': '最短路径为 √5',
          'stem_text': '棱长为一的正方体，沿表面怎样到达相对顶点？',
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
  }) async {
    creations++;
    return {
      'courseware_id': 'cw-1',
      'status': 'ready',
      'state_revision': _stateRev
    };
  }

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
  testWidgets('保存后从我的课件重开不会重复生成', (tester) async {
    final api = _FakeCoursewareApi();
    Widget app(Widget home) => ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: MaterialApp(home: home));
    await tester
        .pumpWidget(app(const GuardianCoursewarePage(promptText: '题目')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('保存课件'));
    await tester.pumpAndSettle();
    expect(find.text('已保存到我的课件'), findsNothing);
    expect(find.text('保存课件'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(app(const CoursewareLibraryPage()));
    await tester.pumpAndSettle();
    expect(find.text('棱长为一的正方体，沿表面怎样到达相对顶点？'), findsOneWidget);
    await tester.tap(find.text('几何备课'));
    await tester.pumpAndSettle();
    expect(find.text('深度课件 · v1'), findsOneWidget);
    expect(find.text('题目'), findsOneWidget);
    expect(
        find.textContaining('沿表面怎样到达相对顶点', findRichText: true), findsWidgets);
    expect(api.creations, 1);
  });
  testWidgets(
      'MentorCoursewarePage renders 3D stage, localized revision, and Undo/Redo',
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

    expect(find.text('微调这一步'), findsNothing);

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

  testWidgets(
      'MathStageView degrades cleanly to static fallback on stage error',
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

  test('computeCoursewareDiff detects added, updated, visual, and deleted steps',
      () {
    final v1 = {
      'current_version': {
        'version_no': 1,
        'change_summary': '初版',
        'steps': [
          {
            'step_id': 's1',
            'title': '1. 审题',
            'thinking_why': '原依据',
            'action_what': '原讲解',
            'content_hash': 'h1',
          },
          {
            'step_id': 's2',
            'title': '2. 展开',
            'thinking_why': '旧依据',
            'action_what': '旧讲解',
            'visual_spec': {'kind': 'component_scene', 'content_hash': 'vis1'},
            'content_hash': 'h2',
          },
          {
            'step_id': 's3',
            'title': '3. 变式拓展',
            'action_what': '长方体变式',
            'content_hash': 'h3',
          },
        ],
      },
    };
    final v2 = {
      'current_version': {
        'version_no': 2,
        'change_summary': '第 2 步更新图文并移除变式',
        'steps': [
          {
            'step_id': 's1',
            'title': '1. 审题',
            'thinking_why': '原依据',
            'action_what': '原讲解',
            'content_hash': 'h1',
          },
          {
            'step_id': 's2',
            'title': '2. 展开',
            'thinking_why': '补充纸盒展开类比',
            'action_what': '新讲解',
            'visual_spec': {'kind': 'component_scene', 'content_hash': 'vis2'},
            'content_hash': 'h2_v2',
          },
          {
            'step_id': 's4',
            'title': '4. 易错提醒',
            'action_what': '注意展开方向',
            'content_hash': 'h4',
          },
        ],
      },
    };

    final diff = computeCoursewareDiff(v1, v2)!;
    expect(diff.versionNo, 2);
    expect(diff.addedStepIds, ['s4']);
    expect(diff.updatedStepIds, ['s2']);
    expect(diff.visualUpdatedStepIds, {'s2'});
    expect(diff.whyUpdatedStepIds, {'s2'});
    expect(diff.actionUpdatedStepIds, {'s2'});
    expect(diff.deletedStepTitles, ['3. 变式拓展']);
  });

  testWidgets(
      'Phase 1 revision shows receipt banner, auto-expands collapsed changed step, and handles undo',
      (tester) async {
    final api = _MultiStepCoursewareApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(
          home: GuardianCoursewarePage(promptText: '正方体表面最短路径'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Initially step 2 is collapsed so its body is not shown
    expect(find.textContaining('旧的第2步讲解', findRichText: true), findsNothing);

    await tester.enterText(find.byType(TextField), '把第2步展开图讲细点并删掉变式');
    await tester.tap(find.byTooltip('提交修订'));
    await tester.pumpAndSettle();

    // Receipt banner visible with summary, changed chip, deleted chip, and quick undo
    expect(find.byKey(const ValueKey('revision-receipt-banner')), findsOneWidget);
    expect(find.textContaining('已更新至 v2 · 第 2 步已补充图示与类比'), findsOneWidget);
    expect(find.textContaining('已移除：3. 变式拓展'), findsOneWidget);
    expect(find.text('定位到改动处'), findsOneWidget);
    expect(find.text('撤销本次修改'), findsOneWidget);

    // Step 2 auto-expanded and shows block-level tags
    expect(find.textContaining('新的第2步讲解', findRichText: true), findsOneWidget);
    expect(find.text('图文已更新'), findsOneWidget);
    expect(find.text('图示已更新'), findsOneWidget);
    expect(find.text('思考依据已补充'), findsOneWidget);
    expect(find.text('讲解已更新'), findsOneWidget);

    // Quick undo from receipt banner restores v1 and clears receipt
    await tester.tap(find.text('撤销本次修改'));
    await tester.pumpAndSettle();
    expect(find.text('深度课件 · v1'), findsOneWidget);
    expect(find.byKey(const ValueKey('revision-receipt-banner')), findsNothing);
  });

  testWidgets('Phase 1 displays failure banner when background revision fails',
      (tester) async {
    final api = _MultiStepCoursewareApi()..failNextRevision = true;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(
          home: GuardianCoursewarePage(promptText: '正方体表面最短路径'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), '把答案改成 3');
    await tester.tap(find.byTooltip('提交修订'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('revision-failure-banner')), findsOneWidget);
    expect(find.textContaining('核验冲突：最短路径仍为 √5'), findsOneWidget);
    expect(find.text('深度课件 · v1'), findsOneWidget);
  });

  testWidgets('Wide screen renders dual-pane layout with revision sidebar',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _MultiStepCoursewareApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiProvider.overrideWithValue(api)],
        child: const MaterialApp(
          home: GuardianCoursewarePage(promptText: '正方体表面最短路径'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('courseware-wide-layout')), findsOneWidget);
    expect(find.byKey(const ValueKey('courseware-wide-sidebar')), findsOneWidget);
    expect(find.text('本轮修订记录'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '把第2步讲细点');
    await tester.tap(find.byTooltip('提交修订'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('revision-receipt-banner')), findsOneWidget);
    expect(find.text('把第2步讲细点'), findsOneWidget);
  });
}

class _MultiStepCoursewareApi extends _FakeCoursewareApi {
  bool failNextRevision = false;
  bool _failedStatus = false;

  @override
  Map<String, dynamic> _buildView() {
    final steps = <Map<String, dynamic>>[
      {
        'step_id': 's1',
        'title': '1. 审题定位',
        'thinking_why': '明确起点与终点',
        'action_what': '正方体棱长为 1。',
        'content_hash': 'h_s1_v1',
      },
      {
        'step_id': 's2',
        'title': '2. 展开侧面',
        'thinking_why': _version == 1 ? '沿棱展平' : '想象把纸盒沿公共棱剪开摊平',
        'action_what': _version == 1 ? '旧的第2步讲解' : '新的第2步讲解（标注中点 M）',
        'visual_spec': {
          'kind': 'component_scene',
          'title': '正方体展开',
          'static_fallback_text': '正方体展开图',
          'content_hash': _version == 1 ? 'vis_v1' : 'vis_v2',
          'payload': {'component': 'solid_geometry_3d', 'shape': 'cube'},
        },
        'content_hash': _version == 1 ? 'h_s2_v1' : 'h_s2_v2',
      },
      if (_version == 1)
        {
          'step_id': 's3',
          'title': '3. 变式拓展',
          'action_what': '换成 1×2×3 长方体',
          'content_hash': 'h_s3_v1',
        },
    ];

    return {
      'courseware_id': 'cw-1',
      'retention_status': saved ? 'saved' : 'temporary',
      'status': 'ready',
      'state_revision': _stateRev,
      'verification_summary': {
        'baseline_hash': 'bh-1',
        'confidence': 'high',
        'summary_answer': '最短路径为 √5',
        'stem_text': '棱长为一的正方体，沿表面怎样到达相对顶点？',
      },
      'current_version': {
        'version_no': _version,
        'baseline_hash': 'bh-1',
        'change_summary': _version == 1 ? '初版' : '第 2 步已补充图示与类比',
        'verification_status': 'verified',
        'methodology_key': '空间展开降维',
        'steps': steps,
      },
      'history_controls': {
        'cursor': _version - 1,
        'total_versions': _version == 1 && revisionCalls == 0 ? 1 : 2,
        'can_undo': _version > 1,
        'can_redo': _version == 1 && revisionCalls > 0,
      },
      'active_revision_pending': false,
    };
  }

  @override
  Future<Map<String, dynamic>> getMentorCoursewareStatus(
      String coursewareId) async {
    if (_failedStatus) {
      return {
        'courseware_id': coursewareId,
        'stage': 'failed',
        'revision_id': 'rev-fail-1',
        'message': '核验冲突：最短路径仍为 √5，原版本保持不变',
      };
    }
    return super.getMentorCoursewareStatus(coursewareId);
  }

  @override
  Future<Map<String, dynamic>> requestMentorCoursewareRevision({
    required String coursewareId,
    required String commandId,
    required String instruction,
    required int baseVersionNo,
    required int expectedStateRevision,
    bool allowUnverifiedOverride = false,
  }) async {
    if (failNextRevision) {
      _failedStatus = true;
      return {
        'courseware_id': coursewareId,
        'revision_id': 'rev-fail-1',
        'base_version_no': baseVersionNo,
        'state_revision': _stateRev,
      };
    }
    _failedStatus = false;
    return super.requestMentorCoursewareRevision(
      coursewareId: coursewareId,
      commandId: commandId,
      instruction: instruction,
      baseVersionNo: baseVersionNo,
      expectedStateRevision: expectedStateRevision,
      allowUnverifiedOverride: allowUnverifiedOverride,
    );
  }
}
