import 'dart:ui';
import 'package:flutter/material.dart';
import '../shared/app_ui.dart';

const Color _tealBrand = Color(0xff0f766e);
const Color _tealBrandLight = Color(0xfff0fdfa);
const Color _orangePause = Color(0xffd97706);
const Color _orangePauseLight = Color(0xfffffbeb);
const Color _textDark = Color(0xff0c1222);
const Color _textMuted = Color(0xff64748b);
const Color _cardBg = Color(0xfff8fafc);
const Color _cardBorder = Color(0xffe2e8f0);

/// 任务信息卡片（展示任务名、时长或时间信息）
Widget _buildTaskCard({
  required String title,
  String? durationText,
  String? details,
  Widget? extraContent,
}) {
  return Container(
    width: double.infinity,
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
    decoration: BoxDecoration(
      color: _cardBg,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: _cardBorder),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          title,
          style: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            color: _textDark,
          ),
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
        ),
        if (details != null && details.trim().isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(
            details,
            style: const TextStyle(fontSize: 12, color: _textMuted),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ],
        if (durationText != null && durationText.trim().isNotEmpty) ...[
          const SizedBox(height: 6),
          Row(
            children: [
              const Icon(Icons.schedule_rounded, size: 14, color: _textMuted),
              const SizedBox(width: 4),
              Text(
                durationText,
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                  color: _textMuted,
                ),
              ),
            ],
          ),
        ],
        if (extraContent != null) ...[
          const SizedBox(height: 8),
          extraContent,
        ],
      ],
    ),
  );
}

/// 弹窗顶部标头（图标徽章 + 标题 + 状态小标签）
Widget _buildDialogHeader({
  required IconData icon,
  required Color iconColor,
  required Color iconBgColor,
  required String title,
  String? pillText,
  Color? pillColor,
}) {
  return Row(
    children: [
      Container(
        width: 36,
        height: 36,
        decoration: BoxDecoration(
          color: iconBgColor,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Icon(icon, size: 20, color: iconColor),
      ),
      const SizedBox(width: 10),
      Expanded(
        child: Text(
          title,
          style: const TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w700,
            color: _textDark,
          ),
        ),
      ),
      if (pillText != null && pillColor != null)
        StatusPill(text: pillText, color: pillColor),
    ],
  );
}

/// 开始学习弹窗
class StartTaskDialog extends StatelessWidget {
  const StartTaskDialog({
    required this.taskTitle,
    required this.isPlanned,
    this.durationText,
    this.details,
    super.key,
  });

  final String taskTitle;
  final bool isPlanned;
  final String? durationText;
  final String? details;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.transparent,
      titlePadding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
      contentPadding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
      actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      title: _buildDialogHeader(
        icon: Icons.play_arrow_rounded,
        iconColor: _tealBrand,
        iconBgColor: _tealBrandLight,
        title: '开始学习？',
        pillText: isPlanned ? '今日计划' : '任务池',
        pillColor: isPlanned ? _tealBrand : Colors.deepPurple,
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildTaskCard(
            title: taskTitle,
            durationText: durationText,
            details: details,
          ),
          const SizedBox(height: 12),
          const Text(
            '开始后你可以随时暂停或完成。',
            style: TextStyle(
              fontSize: 13,
              color: _textMuted,
              height: 1.4,
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          style: TextButton.styleFrom(
            foregroundColor: _textMuted,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          ),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, true),
          style: FilledButton.styleFrom(
            backgroundColor: _tealBrand,
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
          child: const Text('确认开始', style: TextStyle(fontWeight: FontWeight.w600)),
        ),
      ],
    );
  }
}

/// 进行中任务操作弹窗（暂停 / 完成 / 取消）
class ActiveTaskDialog extends StatelessWidget {
  const ActiveTaskDialog({
    required this.taskTitle,
    required this.seconds,
    required this.onPause,
    required this.onFinish,
    this.details,
    super.key,
  });

  final String taskTitle;
  final int seconds;
  final VoidCallback onPause;
  final VoidCallback onFinish;
  final String? details;

  @override
  Widget build(BuildContext context) {
    final minutes = seconds ~/ 60;
    final durationLabel = seconds >= 60 ? '$minutes 分钟' : '$seconds 秒';
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.transparent,
      titlePadding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
      contentPadding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
      actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      title: _buildDialogHeader(
        icon: Icons.timer_outlined,
        iconColor: _tealBrand,
        iconBgColor: _tealBrandLight,
        title: '这项任务正在进行',
        pillText: '进行中',
        pillColor: _tealBrand,
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildTaskCard(
            title: taskTitle,
            details: details,
            extraContent: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0xffe2e8f0)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.av_timer_rounded, size: 18, color: _tealBrand),
                  const SizedBox(width: 6),
                  Text(
                    '已累计 $durationLabel',
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: _tealBrand,
                      fontFeatures: [FontFeature.tabularFigures()],
                    ),
                  ),
                  const Spacer(),
                  const Text(
                    '保持专注',
                    style: TextStyle(fontSize: 11, color: _textMuted),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            '已累计 $minutes 分钟。暂停会保留时长，完成会记下这次学习。',
            style: const TextStyle(
              fontSize: 13,
              color: _textMuted,
              height: 1.4,
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          style: TextButton.styleFrom(
            foregroundColor: _textMuted,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          ),
          child: const Text('取消'),
        ),
        TextButton.icon(
          onPressed: onPause,
          style: TextButton.styleFrom(
            foregroundColor: _orangePause,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          ),
          icon: const Icon(Icons.pause_rounded, size: 18),
          label: const Text('暂停', style: TextStyle(fontWeight: FontWeight.w600)),
        ),
        FilledButton.icon(
          onPressed: onFinish,
          style: FilledButton.styleFrom(
            backgroundColor: _tealBrand,
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
          icon: const Icon(Icons.check_circle_outline_rounded, size: 18),
          label: const Text('完成任务', style: TextStyle(fontWeight: FontWeight.w600)),
        ),
      ],
    );
  }
}

/// 暂停状态操作弹窗（继续 / 完成 / 取消）
class PausedTaskDialog extends StatelessWidget {
  const PausedTaskDialog({
    required this.taskTitle,
    required this.seconds,
    this.details,
    super.key,
  });

  final String taskTitle;
  final int seconds;
  final String? details;

  @override
  Widget build(BuildContext context) {
    final minutes = seconds ~/ 60;
    final durationLabel = seconds >= 60 ? '$minutes 分钟' : '$seconds 秒';
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.transparent,
      titlePadding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
      contentPadding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
      actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      title: _buildDialogHeader(
        icon: Icons.pause_circle_outline_rounded,
        iconColor: _orangePause,
        iconBgColor: _orangePauseLight,
        title: '继续学习？',
        pillText: '已暂停',
        pillColor: _orangePause,
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildTaskCard(
            title: taskTitle,
            details: details,
            extraContent: Row(
              children: [
                const Icon(Icons.history_rounded, size: 16, color: _orangePause),
                const SizedBox(width: 4),
                Text(
                  '已累计学习 $durationLabel（进度已保留）',
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                    color: _orangePause,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            '会继续累计这项任务的学习时长。',
            style: TextStyle(
              fontSize: 13,
              color: _textMuted,
              height: 1.4,
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, 'cancel'),
          style: TextButton.styleFrom(
            foregroundColor: _textMuted,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
          ),
          child: const Text('取消'),
        ),
        TextButton(
          onPressed: () => Navigator.pop(context, 'finish'),
          style: TextButton.styleFrom(
            foregroundColor: _tealBrand,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
          ),
          child: const Text('完成任务'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, 'resume'),
          style: FilledButton.styleFrom(
            backgroundColor: _tealBrand,
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
          child: const Text('确认继续', style: TextStyle(fontWeight: FontWeight.w600)),
        ),
      ],
    );
  }
}

/// 确认完成弹窗
class FinishTaskConfirmDialog extends StatelessWidget {
  const FinishTaskConfirmDialog({
    required this.taskTitle,
    required this.seconds,
    super.key,
  });

  final String taskTitle;
  final int seconds;

  @override
  Widget build(BuildContext context) {
    final minutes = seconds ~/ 60;
    final durationLabel = seconds >= 60 ? '$minutes 分钟' : '$seconds 秒';
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      backgroundColor: Colors.white,
      surfaceTintColor: Colors.transparent,
      titlePadding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
      contentPadding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
      actionsPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      title: _buildDialogHeader(
        icon: Icons.check_circle_rounded,
        iconColor: brandBlue,
        iconBgColor: const Color(0xffeff6ff),
        title: '完成这项任务？',
        pillText: '结算中',
        pillColor: brandBlue,
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildTaskCard(
            title: taskTitle,
            extraContent: Text(
              '本次累计专注时长：$durationLabel',
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: brandBlue,
              ),
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            '完成后会记录本次学习时长。',
            style: TextStyle(
              fontSize: 13,
              color: _textMuted,
              height: 1.4,
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, false),
          style: TextButton.styleFrom(
            foregroundColor: _textMuted,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          ),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, true),
          style: FilledButton.styleFrom(
            backgroundColor: brandBlue,
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
          child: const Text('确认完成', style: TextStyle(fontWeight: FontWeight.w600)),
        ),
      ],
    );
  }
}
