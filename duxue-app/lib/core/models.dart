class Ward {
  const Ward({
    required this.id,
    required this.displayName,
    required this.gradeStage,
    this.notes,
    this.analysisProfileId,
  });
  final String id;
  final String displayName;
  final String gradeStage;
  final String? notes;
  final String? analysisProfileId;
  factory Ward.fromJson(Map<String, dynamic> json) => Ward(
        id: json['id'] as String,
        displayName: json['display_name'] as String,
        gradeStage: json['grade_stage'] as String? ?? 'primary',
        notes: json['notes'] as String?,
        analysisProfileId: json['analysis_profile_id'] as String?,
      );
}

class WeeklyTrend {
  const WeeklyTrend({required this.days});
  final List<WeeklyTrendDay> days;
  factory WeeklyTrend.fromJson(Map<String, dynamic> json) => WeeklyTrend(
        days: (json['days'] as List<dynamic>)
            .map(
              (item) => WeeklyTrendDay.fromJson(
                  Map<String, dynamic>.from(item as Map)),
            )
            .toList(),
      );
}

class WeeklyTrendDay {
  const WeeklyTrendDay({
    required this.date,
    required this.totalSeconds,
    required this.learningSeconds,
  });
  final DateTime date;
  final int totalSeconds;
  final int learningSeconds;
  factory WeeklyTrendDay.fromJson(Map<String, dynamic> json) => WeeklyTrendDay(
        date: DateTime.parse(json['date'].toString()),
        totalSeconds: json['total_seconds'] as int,
        learningSeconds: json['learning_seconds'] as int,
      );
}

class AnalysisProfile {
  const AnalysisProfile({
    required this.id,
    required this.name,
    required this.extraObservationPrompt,
    this.labels = const [],
  });
  final String id;
  final String name;
  final String extraObservationPrompt;
  final List<BehaviorLabel> labels;
  factory AnalysisProfile.fromJson(
    Map<String, dynamic> json,
  ) =>
      AnalysisProfile(
        id: json['id'] as String,
        name: json['name'] as String,
        extraObservationPrompt:
            json['extra_observation_prompt'] as String? ?? '',
        labels: (json['labels'] as List<dynamic>? ?? const [])
            .map(
              (item) => BehaviorLabel.fromJson(
                  Map<String, dynamic>.from(item as Map)),
            )
            .toList(),
      );
}

class BehaviorLabel {
  const BehaviorLabel({
    required this.id,
    required this.name,
    required this.fieldPrototypes,
    required this.priority,
    required this.isActive,
  });
  final String id;
  final String name;
  final Map<String, List<String>> fieldPrototypes;
  final int priority;
  final bool isActive;
  factory BehaviorLabel.fromJson(Map<String, dynamic> json) => BehaviorLabel(
        id: json['id'] as String,
        name: json['label_name'] as String,
        fieldPrototypes:
            (json['field_prototypes'] as Map<String, dynamic>? ?? const {}).map(
          (field, values) => MapEntry(
            field,
            (values as List<dynamic>).map((value) => value.toString()).toList(),
          ),
        ),
        priority: json['priority'] as int? ?? 0,
        isActive: json['is_active'] as bool? ?? true,
      );
}

class Device {
  const Device({required this.id, required this.status, this.lastSeenAt});
  final String id;
  final String status;
  final DateTime? lastSeenAt;
  factory Device.fromJson(Map<String, dynamic> json) => Device(
        id: json['id'],
        status: json['status'],
        lastSeenAt: json['last_seen_at'] == null
            ? null
            : DateTime.parse(json['last_seen_at']),
      );
}

class Segment {
  const Segment({
    required this.start,
    required this.end,
    required this.label,
    required this.confidence,
  });
  final DateTime start;
  final DateTime end;
  final String label;
  final double confidence;
  factory Segment.fromJson(Map<String, dynamic> json) => Segment(
        start: DateTime.parse(json['start']),
        end: DateTime.parse(json['end']),
        label: json['label'],
        confidence: (json['confidence'] as num).toDouble(),
      );
}

class DailyReport {
  const DailyReport({
    required this.status,
    required this.date,
    required this.totalSeconds,
    required this.breakdown,
    required this.timeline,
    required this.profileChanged,
  });
  final String status;
  final DateTime date;
  final int totalSeconds;
  final Map<String, int> breakdown;
  final List<Segment> timeline;
  final bool profileChanged;
  factory DailyReport.fromJson(Map<String, dynamic> json) => DailyReport(
        status: json['status'],
        date: DateTime.parse(json['report_date']),
        totalSeconds: json['total_seconds'],
        breakdown: (json['label_breakdown'] as Map<String, dynamic>).map(
          (key, value) => MapEntry(key, value as int),
        ),
        timeline: (json['timeline_json'] as List)
            .map((item) => Segment.fromJson(item))
            .toList(),
        profileChanged: json['profile_changed'],
      );
}
