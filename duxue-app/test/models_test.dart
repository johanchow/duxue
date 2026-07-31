import 'package:flutter_test/flutter_test.dart';
import 'package:duxue_app/core/models.dart';

void main() {
  test('daily report parses API contract', () {
    final report = DailyReport.fromJson({'status': 'ready', 'report_date': '2026-07-31', 'total_seconds': 30, 'label_breakdown': {'学习': 30}, 'timeline_json': [{'start': '2026-07-31T10:00:00Z', 'end': '2026-07-31T10:00:30Z', 'label': '学习', 'confidence': 1.0}], 'profile_changed': false});
    expect(report.breakdown['学习'], 30); expect(report.timeline.single.label, '学习');
  });
}
