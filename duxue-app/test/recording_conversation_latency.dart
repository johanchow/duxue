import 'package:duxue_app/core/conversation_latency.dart';

class RecordingConversationLatency extends ConversationLatency {
  RecordingConversationLatency() : super('', () async => null, enabled: false);
  final events = <Map<String, dynamic>>[];
  int sends = 0;

  @override
  ConversationTurn start(String entry) =>
      ConversationTurn(entry, 'send-${++sends}', events.add);
}
