import 'package:flutter/material.dart';

import '../core/api_client.dart';

class ConversationPicker extends StatefulWidget {
  const ConversationPicker(
      {super.key, required this.api, this.current, this.adult = false});
  final ApiClient api;
  final String? current;
  final bool adult;
  @override
  State<ConversationPicker> createState() => _ConversationPickerState();
}

class _ConversationPickerState extends State<ConversationPicker> {
  late Future<ConversationPage> items = widget.api.conversationPage();
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
      items = widget.api.conversationPage();
    });
  }

  Future<void> edit(Map<String, dynamic> row, String action) async {
    final id = row['thread_id'] as String;
    if (action == 'ward') {
      await change(() async {
        final wards = await widget.api.wards();
        if (!mounted) return;
        final selected = await showDialog<String>(
            context: context,
            builder: (ctx) =>
                SimpleDialog(title: const Text('关联学生'), children: [
                  for (final ward in wards)
                    SimpleDialogOption(
                        onPressed: () => Navigator.pop(ctx, ward.id),
                        child: Text(ward.displayName)),
                  SimpleDialogOption(
                      onPressed: () => Navigator.pop(ctx, ''),
                      child: const Text('不关联学生')),
                ]));
        if (selected != null) {
          await widget.api
              .setConversationWard(id, selected.isEmpty ? null : selected);
        }
      });
      return;
    }
    if (action == 'summary') {
      await change(() async {
        final data = await widget.api.conversationWardSummary(id);
        if (!mounted) return;
        final events = data['recent_learning_events'] as List;
        await showDialog<void>(
            context: context,
            builder: (ctx) => AlertDialog(
                    title: const Text('近期学情'),
                    content: SingleChildScrollView(
                        child: Text(events.isEmpty
                            ? '暂无可展示的记录'
                            : events
                                .map((e) => e['summary'] == ''
                                    ? '已记录一次学习活动'
                                    : e['summary'])
                                .join('\n'))),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(ctx),
                          child: const Text('关闭'))
                    ]));
      });
      return;
    }
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
        body: FutureBuilder<ConversationPage>(
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
                for (final row in snap.data!.items)
                  ListTile(
                      title: Text(row['title'] as String),
                      selected: widget.current == row['thread_id'],
                      enabled: !busy,
                      onTap: () => Navigator.pop(context, row['thread_id']),
                      trailing: PopupMenuButton<String>(
                          onSelected: (action) => edit(row, action),
                          itemBuilder: (_) => [
                                if (widget.adult)
                                  const PopupMenuItem(
                                      value: 'ward', child: Text('关联学生')),
                                if (widget.adult &&
                                    row['context_ward_id'] != null)
                                  const PopupMenuItem(
                                      value: 'summary', child: Text('近期学情')),
                                const PopupMenuItem(
                                    value: 'rename', child: Text('重命名')),
                                const PopupMenuItem(
                                    value: 'delete', child: Text('删除'))
                              ])),
                if (snap.data!.next case final String cursor)
                  TextButton(
                      onPressed: busy
                          ? null
                          : () async {
                              setState(() => busy = true);
                              try {
                                final page = await widget.api
                                    .conversationPage(cursor: cursor);
                                if (mounted) {
                                  setState(() {
                                    final unique = {
                                      for (final row in [
                                        ...snap.data!.items,
                                        ...page.items
                                      ])
                                        row['thread_id']: row
                                    };
                                    items = Future.value((
                                      items: unique.values.toList(),
                                      next: page.next
                                    ));
                                  });
                                }
                              } catch (_) {
                                if (context.mounted) {
                                  ScaffoldMessenger.of(context).showSnackBar(
                                      const SnackBar(
                                          content: Text('加载失败，请重试')));
                                }
                              } finally {
                                if (mounted) setState(() => busy = false);
                              }
                            },
                      child: const Text('加载更多对话')),
              ]);
            }),
      );
}
