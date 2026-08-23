import 'package:flutter_test/flutter_test.dart';
import 'package:duxue_app/core/models.dart';
import 'package:duxue_app/core/voice_transcription_service.dart';

void main() {
  test('voice transcription derives an authenticated server WebSocket URL', () {
    expect(
      VoiceTranscriptionService.websocketUri('https://duxuelai.xyz/api')
          .toString(),
      'wss://duxuelai.xyz/api/ws/asr/transcribe',
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
