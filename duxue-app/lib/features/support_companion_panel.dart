import 'dart:async';
import 'dart:math';
import 'package:flutter/services.dart';
import '../core/speech_playback.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../providers.dart';

String supportCommandId() {
  final random = Random.secure();
  final bytes = List.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}

/// Foreground delivery of camera invitations. Has no chat or visual surface.
class SupportCompanionPanel extends ConsumerStatefulWidget {
  const SupportCompanionPanel(
      {required this.wardId, this.quietVersion = 0, this.playback, super.key});
  final String wardId;
  final int quietVersion;
  final SpeechPlayback Function()? playback;

  @override
  ConsumerState<SupportCompanionPanel> createState() =>
      _SupportCompanionPanelState();
}

class _SupportCompanionPanelState extends ConsumerState<SupportCompanionPanel>
    with WidgetsBindingObserver {
  final storage = const FlutterSecureStorage();
  SpeechPlayback? player;
  Timer? timer;
  StreamSubscription<void>? completion;
  int generation = 0;
  bool busy = false;
  bool registeredChannel = false;

  bool get foreground =>
      WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    timer = Timer.periodic(const Duration(seconds: 15), (_) => _refresh());
    _refresh();
  }

  void _interrupt() {
    generation++;
    completion?.cancel();
    player?.stop();
  }

  @override
  void didUpdateWidget(SupportCompanionPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.quietVersion != widget.quietVersion) _interrupt();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (foreground) {
      _refresh();
    } else {
      _interrupt();
      if (!busy && registeredChannel) _closeChannel();
    }
  }

  Future<void> _closeChannel() async {
    if (!registeredChannel) return;
    registeredChannel = false;
    busy = true;
    try {
      await ref.read(apiProvider).dio.post('/companion/support-channels',
          data: {'enabled': false, 'handsfree': false});
    } on Exception {
      // A disconnected device also loses its lease after 45 seconds.
    } finally {
      busy = false;
      if (mounted && foreground) _refresh();
    }
  }

  @override
  void dispose() {
    generation++;
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    completion?.cancel();
    player?.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (!foreground || busy) return;
    busy = true;
    final epoch = generation;
    bool active() => mounted && foreground && generation == epoch;
    final dio = ref.read(apiProvider).dio;
    try {
      final registered = await dio.post('/companion/support-channels',
          data: {'enabled': true, 'handsfree': true});
      registeredChannel =
          registered.data is Map && registered.data['id'] is String;
      if (!active() ||
          registered.data is! Map ||
          registered.data['mode'] == 'shadow' ||
          registered.data['id'] is! String) {
        return;
      }
      final channel = registered.data['id'] as String;
      final path = '/companion/support-channels/$channel';
      final response = await dio.get('$path/offer');
      if (!active()) return;
      final offer = response.data['offer'];
      if (offer == null || offer['protocol_version'] != 'support.v1') return;
      final prompt = offer['prompt_id'];
      if (prompt != 'offer_help' && prompt != 'invite_return') return;
      final id = offer['offer_id'] as String;
      final key = 'support-last-played-${widget.wardId}';
      if (await storage.read(key: key) == id || !active()) return;
      final audio = await rootBundle.load('assets/support/$prompt.mp3');
      if (!active()) return;
      final verified = (await dio.get('$path/offer')).data['offer'];
      if (!active() ||
          verified?['offer_id'] != id ||
          !DateTime.parse(verified['expires_at']).isAfter(DateTime.now())) {
        return;
      }
      await storage.write(key: key, value: id);
      if (!active()) return;
      final playback =
          player ??= (widget.playback ?? DeviceSpeechPlayback.new)();
      await completion?.cancel();
      if (!active()) return;
      completion = playback.onComplete.take(1).listen((_) async {
        if (!active()) return;
        try {
          await dio.post('$path/receipts', data: {
            'offer_id': id,
            'receipt_id': supportCommandId(),
            'medium': 'speech_completed',
            'expected_version': verified['version'],
            'presented_at': DateTime.now().toUtc().toIso8601String(),
          });
        } catch (_) {/* An offline or expired offer cannot confirm delivery. */}
      });
      await playback.playMp3(
          audio.buffer.asUint8List(audio.offsetInBytes, audio.lengthInBytes));
    } on Exception {
      // Channel unavailable or audio interrupted. Retry eligible offers on next poll.
    } finally {
      busy = false;
      if (mounted && !foreground && registeredChannel) _closeChannel();
    }
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
