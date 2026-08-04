class Ward {
  const Ward({required this.id, required this.displayName, this.birthYear, this.notes});
  final String id;
  final String displayName;
  final int? birthYear;
  final String? notes;
  factory Ward.fromJson(Map<String, dynamic> json) => Ward(id: json['id'], displayName: json['display_name'], birthYear: json['birth_year'], notes: json['notes']);
}

class Device {
  const Device({required this.id, required this.status, this.lastSeenAt});
  final String id;
  final String status;
  final DateTime? lastSeenAt;
  factory Device.fromJson(Map<String, dynamic> json) => Device(id: json['id'], status: json['status'], lastSeenAt: json['last_seen_at'] == null ? null : DateTime.parse(json['last_seen_at']));
}

class Segment {
  const Segment({required this.start, required this.end, required this.label, required this.confidence});
  final DateTime start;
  final DateTime end;
  final String label;
  final double confidence;
  factory Segment.fromJson(Map<String, dynamic> json) => Segment(start: DateTime.parse(json['start']), end: DateTime.parse(json['end']), label: json['label'], confidence: (json['confidence'] as num).toDouble());
}

class DailyReport {
  const DailyReport({required this.status, required this.date, required this.totalSeconds, required this.breakdown, required this.timeline, required this.profileChanged});
  final String status;
  final DateTime date;
  final int totalSeconds;
  final Map<String, int> breakdown;
  final List<Segment> timeline;
  final bool profileChanged;
  factory DailyReport.fromJson(Map<String, dynamic> json) => DailyReport(
    status: json['status'], date: DateTime.parse(json['report_date']), totalSeconds: json['total_seconds'],
    breakdown: (json['label_breakdown'] as Map<String, dynamic>).map((key, value) => MapEntry(key, value as int)),
    timeline: (json['timeline_json'] as List).map((item) => Segment.fromJson(item)).toList(), profileChanged: json['profile_changed'],
  );
}
