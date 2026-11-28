import 'dart:async';

import 'package:flutter/material.dart';

enum ReplyStage {
  uploading('正在上传图片…'),
  preparing('正在准备回复…'),
  routing('正在理解你的问题…'),
  drafting('正在整理怎么一步步讲…'),
  checking('正在核对这一步提示…'),
  revising('正在调整提示…'),
  rechecking('正在重新核对提示…'),
  reading('正在识别题面…'),
  solving('正在推导解题思路…'),
  explaining('正在整理导师讲解…');

  const ReplyStage(this.label);
  final String label;

  static ReplyStage? fromWire(String stage) => switch (stage) {
        'route' => routing,
        'draft' => drafting,
        'check' => checking,
        'revise' => revising,
        'recheck' => rechecking,
        'read' => reading,
        'solve' => solving,
        'explain' => explaining,
        _ => null,
      };
}

/// The stages describe observable work for this reply.
class ReplyProgress extends StatefulWidget {
  const ReplyProgress({
    super.key,
    required this.stages,
    this.onRevealed,
  }) : assert(stages.length > 0);

  final List<ReplyStage> stages;
  final VoidCallback? onRevealed;

  @override
  State<ReplyProgress> createState() => _ReplyProgressState();
}

class _ReplyProgressState extends State<ReplyProgress>
    with SingleTickerProviderStateMixin {
  static const _delay = Duration(milliseconds: 250);
  static const _rollDuration = Duration(milliseconds: 280);
  static const _visibleRows = 3;
  late final AnimationController _pulse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1500),
  );
  Timer? _revealTimer;
  Timer? _pulseTimer;
  bool _visible = false;

  @override
  void initState() {
    super.initState();
    _revealTimer = Timer(_delay, () {
      setState(() => _visible = true);
      widget.onRevealed?.call();
      _updatePulse();
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _updatePulse();
  }

  void _updatePulse() {
    final animate = _visible &&
        !MediaQuery.disableAnimationsOf(context) &&
        TickerMode.valuesOf(context).enabled;
    if (!animate) {
      _pulseTimer?.cancel();
      _pulseTimer = null;
      _pulse.reset();
    } else if (_pulseTimer == null) {
      _pulse.forward(from: 0);
      _pulseTimer = Timer.periodic(const Duration(seconds: 3), (_) {
        _pulse.forward(from: 0);
      });
    }
  }

  @override
  void dispose() {
    _revealTimer?.cancel();
    _pulseTimer?.cancel();
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_visible) return const SizedBox.shrink();
    final theme = Theme.of(context);
    final style =
        theme.textTheme.bodySmall!.copyWith(fontSize: 13, height: 1.4);
    final rowHeight = MediaQuery.textScalerOf(context).scale(13) * 1.4 + 6;
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    final stages = widget.stages;
    final latest = stages.length - 1;
    final color = theme.colorScheme.onSurface;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Semantics(
        liveRegion: true,
        label: stages.last.label,
        child: ExcludeSemantics(
          child: reduceMotion
              ? Text(stages.last.label, style: style)
              : SizedBox(
                  height: rowHeight * stages.length.clamp(1, _visibleRows),
                  width: double.infinity,
                  child: Stack(
                    children: [
                      for (var index = (latest - _visibleRows).clamp(0, latest);
                          index <= latest;
                          index++)
                        AnimatedPositioned(
                          key: ValueKey(index),
                          duration: _rollDuration,
                          curve: Curves.easeOutCubic,
                          bottom: (latest - index) * rowHeight,
                          height: rowHeight,
                          left: 0,
                          right: 0,
                          child: AnimatedOpacity(
                            duration: _rollDuration,
                            opacity: switch (latest - index) {
                              0 => 1,
                              1 => 0.55,
                              2 => 0.32,
                              _ => 0,
                            },
                            child: TweenAnimationBuilder<double>(
                              tween: Tween(begin: 0.0, end: 1.0),
                              duration: _rollDuration,
                              builder: (context, entry, child) =>
                                  Transform.translate(
                                offset:
                                    Offset(0, (1 - entry) * rowHeight * 0.45),
                                child: Opacity(opacity: entry, child: child),
                              ),
                              child: Align(
                                alignment: AlignmentDirectional.centerStart,
                                child: AnimatedBuilder(
                                  animation: _pulse,
                                  builder: (context, _) {
                                    final breath =
                                        1 - (2 * _pulse.value - 1).abs();
                                    return Text(
                                      stages[index].label,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: style.copyWith(
                                        color: color.withValues(
                                          alpha: 0.86 -
                                              (index == latest
                                                  ? 0.12 * breath
                                                  : 0),
                                        ),
                                      ),
                                    );
                                  },
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
        ),
      ),
    );
  }
}
