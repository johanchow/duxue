import 'package:duxue_app/core/cue_refresh_schedule.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('refresh aligns to the next five-minute wall-clock boundary', () {
    expect(nextCueRefreshDelay(DateTime(2026, 10, 22, 19, 1, 20)),
        const Duration(minutes: 3, seconds: 40));
    expect(nextCueRefreshDelay(DateTime(2026, 10, 22, 19, 5)),
        const Duration(minutes: 5));
    expect(nextCueRefreshDelay(DateTime(2026, 10, 22, 19, 59, 59)),
        const Duration(seconds: 1));
  });
}
