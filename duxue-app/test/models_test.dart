import 'package:flutter_test/flutter_test.dart';
import 'package:duxue_app/core/models.dart';
import 'package:duxue_app/core/voice_transcription_service.dart';
import 'package:duxue_app/main.dart' show appRedirect;
import 'package:duxue_app/providers.dart' show AppSession;
import 'package:duxue_app/features/day_story_pages.dart'
    show wardBindFailureMessage;

void main() {
  test('voice transcription derives an authenticated server WebSocket URL', () {
    expect(
      VoiceTranscriptionService.websocketUri('https://duxuelai.xyz/api')
          .toString(),
      'wss://duxuelai.xyz/api/ws/asr/transcribe',
    );
  });

  test('student binding stays reachable before authentication', () {
    expect(appRedirect(null, '/ward-bind'), isNull);
    expect(appRedirect(null, '/wards'), '/login');
  });

  test('student session is routed only to its own learning space', () {
    const session = AppSession.ward('ward-1');
    expect(appRedirect(session, '/ward-bind'), '/ward-day/ward-1');
    expect(appRedirect(session, '/ward-day/ward-1'), isNull);
    expect(appRedirect(session, '/wards'), '/ward-day/ward-1');
  });

  test(
      'student binding does not mislabel a local post-bind failure as a code error',
      () {
    expect(
      wardBindFailureMessage(StateError('secure storage unavailable')),
      '绑定请求已成功，但本机登录状态保存失败；请查看 Flutter 终端日志。',
    );
  });

  test('ward parses the required grade stage from the API contract', () {
    final ward = Ward.fromJson({
      'id': 'ward-1',
      'display_name': '小读',
      'grade_stage': 'middle',
      'notes': null,
      'analysis_profile_id': null,
    });

    expect(ward.gradeStage, 'middle');
  });

  test('daily report parses API contract', () {
    final report = DailyReport.fromJson({
      'status': 'ready',
      'report_date': '2026-07-31',
      'total_seconds': 30,
      'label_breakdown': {'学习': 30},
      'timeline_json': [
        {
          'start': '2026-07-31T10:00:00Z',
          'end': '2026-07-31T10:00:30Z',
          'label': '学习',
          'confidence': 1.0,
        },
      ],
      'profile_changed': false,
    });
    expect(report.breakdown['学习'], 30);
    expect(report.timeline.single.label, '学习');
  });

  test('weekly trend parses seven-day API data', () {
    final trend = WeeklyTrend.fromJson({
      'days': [
        {'date': '2026-08-01', 'total_seconds': 3600, 'learning_seconds': 2400},
      ],
    });

    expect(trend.days.single.learningSeconds, 2400);
    expect(trend.days.single.date, DateTime(2026, 8, 1));
  });

  test('analysis profile parses form label prototypes', () {
    final profile = AnalysisProfile.fromJson({
      'id': 'profile-1',
      'name': '晚间作业',
      'extra_observation_prompt': '关注离座',
      'labels': [
        {
          'id': 'label-1',
          'label_name': '咬手指',
          'field_prototypes': {
            'hand_action': ['手指放在嘴边'],
          },
          'priority': 10,
          'is_active': true,
        },
      ],
    });

    expect(profile.labels.single.fieldPrototypes['hand_action'], ['手指放在嘴边']);
    expect(profile.labels.single.priority, 10);
  });
}
