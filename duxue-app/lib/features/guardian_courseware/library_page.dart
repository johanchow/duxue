import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../providers.dart';
import 'guardian_courseware_page.dart';
import '../education_document.dart';

class CoursewareLibraryPage extends ConsumerStatefulWidget {
  const CoursewareLibraryPage({super.key});
  @override
  ConsumerState<CoursewareLibraryPage> createState() => _LibraryState();
}

class _LibraryState extends ConsumerState<CoursewareLibraryPage> {
  List<Map<String, dynamic>> rows = [];
  String? next, error, type;
  bool busy = false;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load({bool more = false}) async {
    if (busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final data = await ref
          .read(apiProvider)
          .listSavedCourseware(more ? next : null, type);
      if (!mounted) return;
      setState(() {
        rows = [
          if (more) ...rows,
          ...List<Map<String, dynamic>>.from(data['items'] as List)
        ];
        next = data['next_cursor'] as String?;
      });
    } catch (_) {
      if (mounted) setState(() => error = '读取失败，请重试');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> edit(Map<String, dynamic> row, String action) async {
    String title = row['title'] as String;
    final rename = action == 'rename';
    final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
                title: Text(rename ? '重命名课件' : '删除这份课件？'),
                content: rename
                    ? TextFormField(
                        initialValue: title,
                        maxLength: 80,
                        onChanged: (v) => title = v.trim())
                    : Text(title),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: const Text('取消')),
                  TextButton(
                      onPressed: () => Navigator.pop(ctx, true),
                      child: Text(rename ? '保存' : '删除'))
                ]));
    if (ok != true || !mounted || title.isEmpty) return;
    try {
      await ref.read(apiProvider).changeSavedCourseware(
          row['courseware_id'] as String, action, row['state_revision'] as int,
          title: rename ? title : null);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('操作失败，请刷新重试')));
      }
    }
    if (mounted) await load();
  }

  bool _titleFromQuestion(Map<String, dynamic> row) {
    final title = row['title'] as String;
    final question = row['question_text'] as String? ?? '';
    return title == question ||
        (title.runes.length == 80 && question.startsWith(title));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('我的资源库')),
      body: RefreshIndicator(
          onRefresh: load,
          child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: [
                Wrap(children: [
                  for (final entry in const {
                    'all': '全部',
                    'interactive_courseware': '课件',
                    'grading_report': '批改诊断',
                    'lesson_pack': '备课包'
                  }.entries)
                    ChoiceChip(
                        label: Text(entry.value),
                        selected: (type ?? 'all') == entry.key,
                        onSelected: busy
                            ? null
                            : (_) {
                                setState(() {
                                  type = entry.key == 'all' ? null : entry.key;
                                  rows = [];
                                  next = null;
                                });
                                load();
                              }),
                ]),
                if (busy) const LinearProgressIndicator(),
                if (error != null)
                  TextButton(onPressed: load, child: Text(error!)),
                if (!busy && error == null && rows.isEmpty)
                  const ListTile(title: Text('还没有保存的资源')),
                for (final r in rows)
                  if (r['artifact_type'] == 'lesson_pack' ||
                      r['artifact_type'] == 'grading_report')
                    ListTile(
                        title: Text(r['title'] as String),
                        subtitle: Text(r['artifact_type'] == 'lesson_pack'
                            ? '备课包'
                            : '批改诊断'),
                        onTap: () async {
                          await Navigator.push(
                              context,
                              MaterialPageRoute(
                                  builder: (_) => EducationDocumentPage(
                                      id: r['artifact_id'] as String)));
                          if (mounted) await load();
                        })
                  else
                    ListTile(
                        leading: r['thumbnail'] is String
                            ? Image.memory(
                                base64Decode(r['thumbnail'] as String),
                                width: 48,
                                height: 48,
                                fit: BoxFit.cover)
                            : null,
                        title: Text(
                            (_titleFromQuestion(r)
                                ? r['question_text']
                                : r['title']) as String,
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis),
                        subtitle: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (r['question_text'] is String &&
                                  !_titleFromQuestion(r))
                                Text(r['question_text'] as String,
                                    maxLines: 3,
                                    overflow: TextOverflow.ellipsis),
                              Text([
                                if (r['subject'] != null &&
                                    r['subject'] != 'general')
                                  r['subject'],
                                (r['updated_at'] as String).split('T').first
                              ].join(' · ')),
                            ]),
                        onTap: () async {
                          await Navigator.push(
                              context,
                              MaterialPageRoute<void>(
                                  builder: (_) => GuardianCoursewarePage(
                                      promptText: '',
                                      initialCoursewareId:
                                          r['courseware_id'] as String)));
                          if (mounted) await load();
                        },
                        trailing: PopupMenuButton<String>(
                            onSelected: (v) => edit(r, v),
                            itemBuilder: (_) => const [
                                  PopupMenuItem(
                                      value: 'rename', child: Text('重命名')),
                                  PopupMenuItem(
                                      value: 'delete', child: Text('删除'))
                                ])),
                if (next != null)
                  TextButton(
                      onPressed: busy ? null : () => load(more: true),
                      child: const Text('加载更多'))
              ])));
}
