import 'package:flutter/material.dart';

/// 到点开始邀请。只渲染服务端给出的 `presented` 卡片和允许的按钮。
class StartCueCard extends StatelessWidget {
  const StartCueCard({
    super.key,
    required this.text,
    required this.tasks,
    required this.actions,
    required this.onCommand,
  });

  final String text;
  final List<Map<String, dynamic>> tasks;
  final List<Map<String, dynamic>> actions;
  final ValueChanged<String> onCommand;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0x1a0f172a)),
        boxShadow: const [
          BoxShadow(color: Color(0x140c1222), blurRadius: 24, offset: Offset(0, 8)),
        ],
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const Text('到点了',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Color(0xff115e59))),
        const SizedBox(height: 8),
        Text(text, style: const TextStyle(fontSize: 16, height: 1.45, fontWeight: FontWeight.w500, color: Color(0xff0c1222))),
        if (tasks.isNotEmpty) ...[
          const SizedBox(height: 12),
          for (final task in tasks) _task(task),
        ],
        const SizedBox(height: 8),
        for (final action in actions) _button(action),
      ]),
    );
  }

  Widget _task(Map<String, dynamic> task) {
    final due = task['due'] == true;
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: due ? const Color(0xffe6f4f1) : const Color(0xfff4f6f8),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(task['title'] as String? ?? '',
          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
    );
  }

  Widget _button(Map<String, dynamic> action) {
    final command = action['command'] as String? ?? '';
    final label = action['label'] as String? ?? command;
    final quiet = action['quiet'] == true;
    if (quiet) {
      return TextButton(onPressed: () => onCommand(command), child: Text(label));
    }
    if (action['primary'] == true) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xff0f766e),
            minimumSize: const Size.fromHeight(46),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          ),
          onPressed: () => onCommand(command),
          child: Text(label),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: OutlinedButton(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size.fromHeight(46),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        ),
        onPressed: () => onCommand(command),
        child: Text(label, style: const TextStyle(color: Color(0xff0c1222))),
      ),
    );
  }
}
