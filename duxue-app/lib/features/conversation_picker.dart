import 'package:flutter/material.dart';

import '../core/api_client.dart';

class ConversationPicker extends StatefulWidget {
  const ConversationPicker({super.key, required this.api, this.current});
  final ApiClient api;
  final String? current;
  @override
  State<ConversationPicker> createState() => _ConversationPickerState();
}

class _ConversationPickerState extends State<ConversationPicker> {
  late Future<List<Map<String, dynamic>>> items = widget.api.conversations();
  bool busy = false;
  Future<void> change(Future<void> Function() action) async {
    if (busy) return;
    setState(() => busy = true);
    try {
      await action();
      if (mounted && ModalRoute.of(context)?.isCurrent == true) reload();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('操作失败，请重试')));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void reload() {
    setState(() {
      items = widget.api.conversations();
    });
  }

  Future<void> edit(Map<String, dynamic> row, String action) async {
    final id = row['thread_id'] as String;
    var title = row['title'] as String;
    final deleting = action == 'delete';
    final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
              title: Text(deleting ? '删除这个对话？' : '重命名对话'),
              content: deleting
                  ? const Text('已保存的作品和课件仍可在资源库打开。')
                  : TextFormField(
                      initialValue: title,
                      autofocus: true,
                      maxLength: 80,
                      onChanged: (s) => title = s.trim()),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Text('取消')),
                TextButton(
                    onPressed: () => Navigator.pop(ctx, true),
                    child: Text(deleting ? '删除' : '保存'))
              ],
            ));
    if (ok != true || !mounted) return;
    await change(() async {
      if (deleting) {
        await widget.api.deleteConversation(id);
        if (id == widget.current && mounted) Navigator.pop(context, '');
      } else if (title.isNotEmpty) {
        await widget.api.renameConversation(id, title);
      }
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('历史对话')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
            future: items,
            builder: (ctx, snap) {
              if (snap.hasError) {
                return Center(
                    child: TextButton(
                        onPressed: reload, child: const Text('重新加载')));
              }
              if (!snap.hasData) {
                return const Center(child: CircularProgressIndicator());
              }
              return ListView(children: [
                ListTile(
                    leading: const Icon(Icons.add),
                    title: const Text('新建对话'),
                    enabled: !busy,
                    onTap: () => change(() async {
                          final row = await widget.api.createConversation();
                          if (context.mounted) {
                            Navigator.pop(context, row['thread_id']);
                          }
                        })),
                for (final row in snap.data!)
                  ListTile(
                      title: Text(row['title'] as String),
                      selected: widget.current == row['thread_id'],
                      enabled: !busy,
                      onTap: () => Navigator.pop(context, row['thread_id']),
                      trailing: PopupMenuButton<String>(
                          onSelected: (action) => edit(row, action),
                          itemBuilder: (_) => const [
                                PopupMenuItem(
                                    value: 'rename', child: Text('重命名')),
                                PopupMenuItem(
                                    value: 'delete', child: Text('删除'))
                              ])),
              ]);
            }),
      );
}
