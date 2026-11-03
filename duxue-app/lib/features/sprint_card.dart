import 'dart:async';
import 'package:flutter/material.dart';

/// Presentation of server-confirmed time only. It never completes a task.
class SprintCard extends StatefulWidget {
  const SprintCard(
      {required this.sprint,
      required this.onAction,
      required this.onHide,
      required this.onElapsed,
      this.busy = false,
      super.key});
  final Map<String, dynamic> sprint;
  final Future<void> Function(String) onAction;
  final VoidCallback onHide;
  final VoidCallback onElapsed;
  final bool busy;
  @override
  State<SprintCard> createState() => _SprintCardState();
}

class _SprintCardState extends State<SprintCard> {
  Timer? timer;
  int ticks = 0;
  bool notified = false;
  @override
  void initState() {
    super.initState();
    _reset();
  }

  @override
  void didUpdateWidget(SprintCard old) {
    super.didUpdateWidget(old);
    if (!identical(old.sprint, widget.sprint)) _reset();
  }

  void _reset() {
    timer?.cancel();
    ticks = 0;
    notified = false;
    if (widget.sprint['status'] == 'active') {
      timer = Timer.periodic(const Duration(seconds: 1), (clock) {
        if (!mounted) return;
        setState(() => ticks = clock.tick);
        if (_remaining <= 0 && !notified) {
          notified = true;
          timer?.cancel();
          widget.onElapsed();
        }
      });
    }
  }

  int get _remaining =>
      ((widget.sprint['remaining_seconds'] as num?)?.toInt() ?? 0) - ticks;
  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final remaining = _remaining;
    if (remaining <= 0) return const SizedBox.shrink();
    final paused = widget.sprint['status'] == 'paused';
    return Card(
        key: const Key('active-sprint-card'),
        child: Padding(
            padding: const EdgeInsets.all(12),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${widget.sprint['topic']} · 专注挑战',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              Text(paused ? '本轮已暂停' : '本轮剩余 ${(remaining / 60).ceil()} 分钟'),
              Wrap(children: [
                TextButton(
                    onPressed: widget.busy
                        ? null
                        : () => widget.onAction(paused ? 'resume' : 'pause'),
                    child: Text(paused ? '继续本轮' : '暂停本轮')),
                TextButton(
                    onPressed:
                        widget.busy ? null : () => widget.onAction('end'),
                    child: const Text('结束本轮')),
                TextButton(onPressed: widget.onHide, child: const Text('收起')),
              ]),
            ])));
  }
}

class SprintSetupDialog extends StatefulWidget {
  const SprintSetupDialog({this.topic = '学习', this.minutes = 20, super.key});
  final String topic;
  final int minutes;
  @override
  State<SprintSetupDialog> createState() => _SprintSetupDialogState();
}

class _SprintSetupDialogState extends State<SprintSetupDialog> {
  late final topic = TextEditingController(text: widget.topic);
  late final minutes = TextEditingController(text: '${widget.minutes}');
  String? error;
  @override
  void dispose() {
    topic.dispose();
    minutes.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
          title: const Text('试一轮专注挑战'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(
                controller: topic,
                decoration: const InputDecoration(labelText: '这轮做什么')),
            TextField(
                controller: minutes,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: '挑战分钟数（1–180）')),
            const Text('到时只结束本轮，不代表作业完成。'),
            if (error != null) Text(error!),
          ]),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('先不用')),
            FilledButton(
                onPressed: () {
                  final target = int.tryParse(minutes.text);
                  if (topic.text.trim().isEmpty ||
                      target == null ||
                      target < 1 ||
                      target > 180) {
                    setState(() => error = '请填写主题与1至180分钟时长');
                    return;
                  }
                  Navigator.pop(
                      context, {'topic': topic.text.trim(), 'minutes': target});
                },
                child: const Text('开始这次挑战'))
          ]);
}
