import 'dart:async';
import 'package:flutter/material.dart';

/// Shared visual shell for intake, confirmation and the running round.
class SprintPanel extends StatelessWidget {
  const SprintPanel(
      {required this.title,
      required this.child,
      required this.onClose,
      required this.closeLabel,
      this.subtitle,
      this.trailing,
      super.key});
  final String title;
  final Widget child;
  final VoidCallback? onClose;
  final String closeLabel;
  final String? subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dark = theme.brightness == Brightness.dark;
    final accent = dark ? const Color(0xff72ddcb) : const Color(0xff0f766e);
    return Theme(
      data: theme.copyWith(
          colorScheme: theme.colorScheme.copyWith(
        primary: accent,
        onPrimary: dark ? const Color(0xff00382f) : Colors.white,
      )),
      child: Container(
        width: double.infinity,
        decoration: BoxDecoration(
          gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: dark
                  ? const [Color(0xff183a35), Color(0xff172925)]
                  : const [Color(0xffe6f5ef), Color(0xfff8fcfa)]),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: accent.withValues(alpha: .22)),
          boxShadow: [
            BoxShadow(
                color: accent.withValues(alpha: dark ? .06 : .10),
                blurRadius: 16,
                offset: const Offset(0, 4))
          ],
        ),
        padding: const EdgeInsets.all(12),
        child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(children: [
                Container(
                    padding: const EdgeInsets.all(7),
                    decoration: BoxDecoration(
                        color: accent.withValues(alpha: .10),
                        borderRadius: BorderRadius.circular(10)),
                    child: Icon(Icons.local_fire_department_outlined,
                        color: accent, size: 18)),
                const SizedBox(width: 8),
                Expanded(
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                      Text(title,
                          style: TextStyle(
                              fontSize: 15,
                              height: 1.4,
                              fontWeight: FontWeight.w700,
                              color: accent)),
                      if (subtitle != null)
                        Text(subtitle!,
                            style: TextStyle(
                                fontSize: 11, height: 1.3, color: accent)),
                    ])),
                if (trailing != null) ...[
                  const SizedBox(width: 8),
                  SizedBox(width: 76, child: trailing!),
                ],
                const SizedBox(width: 4),
                IconButton(
                    onPressed: onClose,
                    tooltip: closeLabel,
                    icon: Icon(Icons.close_rounded, color: accent, size: 21)),
              ]),
              const SizedBox(height: 6),
              child,
            ]),
      ),
    );
  }
}

/// One clock shared by the header and card; hiding either never resets time.
class SprintCountdown extends ValueNotifier<int> {
  SprintCountdown({required this.onElapsed}) : super(0);
  final VoidCallback onElapsed;
  Timer? _timer;

  void update(Map<String, dynamic>? sprint) {
    _timer?.cancel();
    final remaining = (sprint?['remaining_seconds'] as num?)?.toInt() ?? 0;
    value = remaining > 0 ? remaining : 0;
    if (sprint?['status'] != 'active' || remaining <= 0) return;
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      final next = remaining - timer.tick;
      value = next > 0 ? next : 0;
      if (next <= 0) {
        timer.cancel();
        onElapsed();
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

String sprintTimeLabel(int remaining) =>
    '${remaining ~/ 60}:${(remaining % 60).toString().padLeft(2, '0')}';

/// Presentation of server-confirmed time only. It never completes a task.
class SprintCard extends StatefulWidget {
  const SprintCard(
      {required this.sprint,
      required this.onAction,
      required this.onHide,
      required this.onElapsed,
      this.busy = false,
      this.countdown,
      super.key});
  final Map<String, dynamic> sprint;
  final Future<void> Function(String) onAction;
  final VoidCallback onHide;
  final VoidCallback onElapsed;
  final bool busy;
  final SprintCountdown? countdown;
  @override
  State<SprintCard> createState() => _SprintCardState();
}

class _SprintCardState extends State<SprintCard> {
  late SprintCountdown _clock;
  bool get _ownsClock => widget.countdown == null;

  void _attachClock() {
    _clock = widget.countdown ??
        SprintCountdown(onElapsed: () => widget.onElapsed());
    if (_ownsClock) _clock.update(widget.sprint);
  }

  @override
  void initState() {
    super.initState();
    _attachClock();
  }

  @override
  void didUpdateWidget(SprintCard old) {
    super.didUpdateWidget(old);
    if (old.countdown != widget.countdown) {
      if (old.countdown == null) _clock.dispose();
      _attachClock();
    } else if (_ownsClock && !identical(old.sprint, widget.sprint)) {
      _clock.update(widget.sprint);
    }
  }

  @override
  void dispose() {
    if (_ownsClock) _clock.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ValueListenableBuilder<int>(
      valueListenable: _clock,
      builder: (context, remaining, _) => _buildCard(context, remaining));

  Widget _buildCard(BuildContext context, int remaining) {
    if (remaining <= 0) return const SizedBox.shrink();
    final paused = widget.sprint['status'] == 'paused';
    final target = (widget.sprint['target_seconds'] as num?)?.toInt();
    final fraction = target != null && target > 0
        ? (remaining / target).clamp(0.0, 1.0)
        : null;
    final time = sprintTimeLabel(remaining);
    final dark = Theme.of(context).brightness == Brightness.dark;
    final accent = dark ? const Color(0xff72ddcb) : const Color(0xff0f766e);
    final actionStyle = FilledButton.styleFrom(
        backgroundColor: accent.withValues(alpha: .12),
        foregroundColor: accent,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        minimumSize: const Size(0, 40));
    return SprintPanel(
        key: const Key('active-sprint-card'),
        title: widget.sprint['topic'] == '专注挑战'
            ? '专注挑战'
            : '${widget.sprint['topic']} · 专注挑战',
        onClose: widget.onHide,
        closeLabel: '收起挑战',
        subtitle: paused ? '本轮已暂停' : '本轮剩余',
        trailing: FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerRight,
          child: Semantics(
              label: '剩余 ${remaining ~/ 60} 分 ${remaining % 60} 秒',
              child: ExcludeSemantics(
                  child: Text(time,
                      style: TextStyle(
                          fontSize: 24,
                          height: 1.15,
                          color: accent,
                          fontWeight: FontWeight.w700,
                          fontFeatures: const [
                            FontFeature.tabularFigures()
                          ])))),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (fraction != null) ...[
            LinearProgressIndicator(
              key: const Key('sprint-remaining-progress'),
              value: fraction,
              minHeight: 6,
              borderRadius: BorderRadius.circular(8),
              color: accent.withValues(alpha: paused ? .45 : 1),
              backgroundColor: accent.withValues(alpha: .10),
              semanticsLabel: '本轮剩余时间',
              semanticsValue: '${(fraction * 100).round()}%',
            ),
          ],
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 4, children: [
            FilledButton.icon(
                style: actionStyle,
                onPressed: widget.busy
                    ? null
                    : () => widget.onAction(paused ? 'resume' : 'pause'),
                icon: Icon(
                    paused ? Icons.play_arrow_rounded : Icons.pause_rounded,
                    size: 20),
                label: Text(paused ? '继续本轮' : '暂停本轮')),
            FilledButton.icon(
                style: actionStyle,
                onPressed: widget.busy ? null : () => widget.onAction('end'),
                icon: const Icon(Icons.stop_rounded, size: 20),
                label: const Text('结束本轮')),
          ]),
        ]));
  }
}
