import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers.dart';

class EducationDocumentPage extends ConsumerStatefulWidget {
  const EducationDocumentPage({required this.id, super.key});
  final String id;
  @override
  ConsumerState<EducationDocumentPage> createState() => _DocumentState();
}

class _DocumentState extends ConsumerState<EducationDocumentPage> {
  Map<String, dynamic>? doc;
  String? error;
  bool busy = false;
  final edit = TextEditingController();
  String? retryKey, commandId;

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    edit.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final value = await ref.read(apiProvider).educationDocument(widget.id);
      if (mounted) {
        setState(() {
          doc = value;
          error = null;
        });
      }
    } catch (_) {
      if (mounted) setState(() => error = '读取失败，请重试');
    }
  }

  Future<void> change(String action) async {
    if (busy || doc == null) return;
    final text = edit.text.trim();
    if (action == 'revise' && text.isEmpty) return;
    final revision = doc!['state_revision'];
    final key = '$action/$revision/$text';
    if (key != retryKey) {
      commandId = DateTime.now().microsecondsSinceEpoch.toString();
      retryKey = key;
    }
    setState(() => busy = true);
    try {
      final value =
          await ref.read(apiProvider).changeEducationDocument(widget.id, {
        'action': action,
        'expected_revision': revision,
        'command_id': commandId,
        if (action == 'revise') 'instruction': text,
      });
      if (mounted) {
        setState(() {
          doc = value;
          error = null;
          retryKey = null;
          if (action == 'revise') edit.clear();
        });
      }
    } catch (_) {
      await load();
      if (mounted) setState(() => error = '操作未完成，请重试');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = doc;
    return Scaffold(
        appBar: AppBar(title: Text(data?['title'] as String? ?? '教学资源')),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          if (busy || data == null && error == null)
            const LinearProgressIndicator(),
          if (error != null) TextButton(onPressed: load, child: Text(error!)),
          if (data != null) ...[
            for (final block in data['blocks'] as List)
              if (block['kind'] == 'teaching_notes')
                SelectableText(block['text'] as String)
              else
                Card(
                    child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text([
                                if (block['page'] != null)
                                  '第 ${block['page']} 页',
                                '第 ${block['label']} 项'
                              ].join(' · ')),
                              SelectableText(block['stem'] as String),
                              if (block['student_answer'] != null)
                                Text('学生作答：${block['student_answer']}'),
                              Text(const {
                                    'correct': '正确',
                                    'incorrect': '有误',
                                    'verified': '已自验',
                                    'needs_manual_review': '待人工复核'
                                  }[block['status']] ??
                                  '待人工复核'),
                              if (block['reference_answers'] is Map)
                                SelectableText(
                                    '参考答案：${(block['reference_answers'] as Map).values.join('；')}'),
                              if (block['explanation'] != null)
                                Text(block['explanation'] as String),
                            ]))),
            Wrap(children: [
              TextButton(
                  onPressed: busy || data['saved'] == true
                      ? null
                      : () => change('save'),
                  child: Text(data['saved'] == true ? '已保存' : '保存到我的资源库')),
              TextButton(
                  onPressed: !busy && data['can_undo'] == true
                      ? () => change('undo')
                      : null,
                  child: const Text('撤销')),
              TextButton(
                  onPressed: !busy && data['can_redo'] == true
                      ? () => change('redo')
                      : null,
                  child: const Text('重做'))
            ]),
            TextField(
                controller: edit,
                enabled: !busy,
                decoration: InputDecoration(
                    labelText: '修订要求',
                    suffixIcon: IconButton(
                        onPressed: busy ? null : () => change('revise'),
                        icon: const Icon(Icons.send)))),
          ],
        ]));
  }
}
