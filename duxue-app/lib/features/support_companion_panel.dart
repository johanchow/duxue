import 'dart:async';
import 'dart:math';
import 'package:audioplayers/audioplayers.dart';
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

/// An explicitly opened foreground channel; never opens the microphone.
class SupportCompanionPanel extends ConsumerStatefulWidget {
  const SupportCompanionPanel(
      {required this.wardId, required this.onAsk, super.key});
  final String wardId;
  final VoidCallback onAsk;
  @override
  ConsumerState<SupportCompanionPanel> createState() =>
      _SupportCompanionPanelState();
}

class _SupportCompanionPanelState extends ConsumerState<SupportCompanionPanel>
    with WidgetsBindingObserver {
  bool enabled = false, handsfree = false, busy = false, foreground = true;
  int generation = 0;
  String? channel, error;
  Map<String, dynamic>? offer;
  AudioPlayer? _player;
  AudioPlayer get player => _player ??= AudioPlayer();
  final storage = const FlutterSecureStorage();
  Timer? timer, expiry;
  StreamSubscription<void>? completion;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    timer = Timer.periodic(const Duration(seconds: 15), (_) => _refresh());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    foreground = state == AppLifecycleState.resumed;
    generation++;
    if (!foreground) {
      _player?.stop();
      completion?.cancel();
      if (mounted) setState(() => offer = null);
      _close();
    } else if (enabled) {
      _refresh();
    }
  }

  Future<void> _close() async {
    if (channel == null) return;
    try {
      await ref.read(apiProvider).dio.post('/companion/support-channels',
          data: {'enabled': false, 'handsfree': false});
    } catch (_) {/* Server lease expires even when the client is offline. */}
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    generation++;
    timer?.cancel();
    expiry?.cancel();
    completion?.cancel();
    _player?.dispose();
    super.dispose();
  }

  Future<void> _toggle(bool value) async {
    generation++;
    if (!value) {
      await _player?.stop();
      await completion?.cancel();
      await _close();
      if (mounted) {
        setState(() {
          enabled = false;
          offer = null;
        });
      }
      return;
    }
    setState(() => enabled = true);
    await _refresh();
  }

  Future<void> _refresh() async {
    if (!enabled || !foreground || busy) return;
    final epoch = generation;
    busy = true;
    try {
      final api = ref.read(apiProvider);
      final registered = await api.dio.post('/companion/support-channels',
          data: {'enabled': true, 'handsfree': handsfree});
      if (!mounted || epoch != generation || !foreground) return;
      channel = registered.data['id'] as String;
      final response =
          await api.dio.get('/companion/support-channels/$channel/offer');
      if (!mounted || epoch != generation || !foreground) return;
      final next = response.data['offer'] as Map<String, dynamic>?;
      if (next != null &&
          (next['protocol_version'] != 'support.v1' ||
              !DateTime.parse(next['expires_at'] as String)
                  .isAfter(DateTime.now()))) {
        throw StateError('unsupported or expired invitation');
      }
      expiry?.cancel();
      if (next != null) {
        expiry = Timer(
            DateTime.parse(next['expires_at'] as String)
                .difference(DateTime.now()), () {
          if (!mounted) return;
          generation++;
          completion?.cancel();
          _player?.stop();
          setState(() => offer = null);
        });
      }
      final isNew = next != null && next['offer_id'] != offer?['offer_id'];
      setState(() {
        offer = next;
        error = null;
      });
      if (!isNew) return;
      WidgetsBinding.instance.addPostFrameCallback((_) async {
        if (!mounted || epoch != generation || !foreground || offer == null) {
          return;
        }
        try {
          final receipt = await _receipt('card_rendered');
          if (!mounted || epoch != generation || offer == null) return;
          offer!['version'] = receipt['version'];
          if (handsfree) await _play(epoch);
        } catch (_) {
          if (mounted) setState(() => offer = null);
        }
      });
    } catch (_) {
      if (mounted && epoch == generation) {
        setState(() {
          error = '陪伴暂时无法连接';
          offer = null;
        });
      }
    } finally {
      busy = false;
    }
  }

  Future<Map<String, dynamic>> _receipt(String medium) async {
    final result = await ref
        .read(apiProvider)
        .dio
        .post('/companion/support-channels/$channel/receipts', data: {
      'offer_id': offer!['offer_id'],
      'receipt_id': supportCommandId(),
      'medium': medium,
      'presented_at': DateTime.now().toUtc().toIso8601String(),
      'expected_version': offer!['version'],
    });
    return Map<String, dynamic>.from(result.data as Map);
  }

  Future<void> _play(int epoch) async {
    final current = offer;
    if (current == null || !foreground || !handsfree) return;
    final prompt = current['prompt_id'];
    if (prompt != 'offer_help' && prompt != 'invite_return') return;
    final key = 'support-last-played-${widget.wardId}';
    if (await storage.read(key: key) == current['offer_id']) return;
    // Persist before playback: interruption/restart must not repeat the phrase.
    await storage.write(key: key, value: current['offer_id'] as String);
    if (!mounted || epoch != generation || !foreground || !handsfree) return;
    await completion?.cancel();
    completion = player.onPlayerComplete.listen((_) async {
      if (!mounted ||
          epoch != generation ||
          !foreground ||
          !handsfree ||
          offer?['offer_id'] != current['offer_id']) {
        return;
      }
      try {
        await _receipt('speech_completed');
      } catch (_) {/* Never invent completion after a failed receipt. */}
    });
    await player.play(AssetSource('support/$prompt.mp3'));
  }

  Future<void> _respond(String action) async {
    final current = offer;
    if (current == null) return;
    try {
      final response = await ref
          .read(apiProvider)
          .dio
          .post('/study/help-offers/${current['offer_id']}/responses', data: {
        'action': action,
        'expected_version': current['version'],
        'command_id': supportCommandId()
      });
      if (!mounted) return;
      await _player?.stop();
      setState(() => offer = null);
      if (response.data['focus_composer'] == true) widget.onAsk();
    } catch (_) {
      if (mounted) {
        setState(() {
          offer = null;
          error = '邀请已更新，请稍后再试';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) =>
      Column(mainAxisSize: MainAxisSize.min, children: [
        SwitchListTile(
            title: const Text('开启陪伴提示'),
            value: enabled,
            onChanged: busy ? null : _toggle),
        if (enabled)
          SwitchListTile(
              title: const Text('轻声提示'),
              value: handsfree,
              onChanged: (value) {
                setState(() => handsfree = value);
                if (!value) {
                  completion?.cancel();
                  _player?.stop();
                }
                _refresh();
              }),
        if (error != null) Text(error!),
        if (offer != null)
          Card(
              child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(children: [
                    Text(offer!['text'] as String),
                    Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                      TextButton(
                          onPressed: () => _respond('decline_help'),
                          child: const Text('暂时不用')),
                      FilledButton(
                          onPressed: () => _respond('accept_help'),
                          child: const Text('好')),
                    ]),
                  ]))),
      ]);
}
