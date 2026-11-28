import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import '../shared/voice_composer.dart';
import 'visual_block.dart';

class WardWorksLibrary extends ConsumerStatefulWidget {
  const WardWorksLibrary({super.key});

  @override
  ConsumerState<WardWorksLibrary> createState() => _LibraryState();
}

class _LibraryState extends ConsumerState<WardWorksLibrary> {
  late Future<List<Map<String, dynamic>>> rows =
      ref.read(apiProvider).savedWorks();

  bool changing = false;

  Future<void> edit(Map<String, dynamic> row, String action) async {
    if (changing) return;
    final deleting = action == 'delete';
    var title = row['title'] as String;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(deleting ? '删除《$title》？' : '重命名作品'),
        content: deleting
            ? null
            : TextFormField(
                initialValue: title,
                autofocus: true,
                maxLength: 80,
                onChanged: (value) => title = value.trim()),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(deleting ? '删除' : '保存')),
        ],
      ),
    );
    if (confirmed != true || !mounted || title.isEmpty) return;
    setState(() => changing = true);
    try {
      final api = ref.read(apiProvider);
      final id = row['artifact_id'] as String;
      if (deleting) {
        await api.deleteCreativeWork(id);
      } else {
        await api.renameCreativeWork(id, title);
      }
      if (mounted) setState(() => rows = api.savedWorks());
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('作品更新失败，请重试')));
      }
    } finally {
      if (mounted) setState(() => changing = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('我的作品')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
          future: rows,
          builder: (context, snapshot) {
            if (snapshot.hasError) {
              return Center(
                  child: TextButton(
                      onPressed: () {
                        setState(() {
                          rows = ref.read(apiProvider).savedWorks();
                        });
                      },
                      child: const Text('重新加载')));
            }
            if (!snapshot.hasData) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.data!.isEmpty) {
              return const Center(child: Text('保存的作品会出现在这里'));
            }
            return ListView(children: [
              for (final row in snapshot.data!)
                ListTile(
                    leading: const Icon(Icons.menu_book),
                    title: Text(row['title'] as String),
                    trailing: PopupMenuButton<String>(
                        enabled: !changing,
                        onSelected: (value) => edit(row, value),
                        itemBuilder: (_) => const [
                              PopupMenuItem(
                                  value: 'rename', child: Text('重命名')),
                              PopupMenuItem(value: 'delete', child: Text('删除')),
                            ]),
                    onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) => WardStoryPage(
                                id: row['artifact_id'] as String))))
            ]);
          }));
}

class WardStoryPage extends ConsumerStatefulWidget {
  const WardStoryPage({super.key, required this.id});
  final String id;

  @override
  ConsumerState<WardStoryPage> createState() => _StoryState();
}

class _StoryState extends ConsumerState<WardStoryPage> {
  Map<String, dynamic>? work;
  bool busy = false;
  int page = 0;
  String? error, lastRequest, commandId;
  final instruction = TextEditingController();

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    instruction.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final data = await ref.read(apiProvider).creativeWork(widget.id);
      if (mounted) {
        setState(() {
          work = data;
          error = null;
        });
      }
    } catch (_) {
      if (mounted) setState(() => error = '作品加载失败');
    }
  }

  Future<void> change(String action, [String? text]) async {
    if (busy ||
        work == null ||
        (action == 'revise' && (text ?? '').trim().isEmpty)) {
      return;
    }
    final current = work!;
    final version = current['state_revision'] as int;
    final block = current['pages'][page]['block_id'] as String;
    final key = [version, action, block, text].join('|');
    if (key != lastRequest) {
      lastRequest = key;
      commandId = DateTime.now().microsecondsSinceEpoch.toString();
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final data = await ref.read(apiProvider).changeCreativeWork(widget.id, {
        'action': action,
        'expected_revision': version,
        'command_id': commandId,
        if (action == 'revise') ...{
          'instruction': text!.trim(),
          'block_id': block
        },
      });
      if (mounted) {
        setState(() {
          work = data;
          lastRequest = null;
          instruction.clear();
        });
      }
    } on DioException catch (e) {
      if (e.response?.statusCode == 409) await load();
      final detail = e.response?.data;
      if (mounted) {
        setState(() => error = e.response?.statusCode == 422 &&
                detail is Map &&
                detail['detail'] is String
            ? detail['detail'] as String
            : '操作未完成，请重试');
      }
    } catch (_) {
      if (mounted) setState(() => error = '操作未完成，请重试');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final current = work;
    return Scaffold(
        appBar: AppBar(title: Text(current?['title'] as String? ?? '绘本')),
        body: current == null
            ? Center(
                child: error == null
                    ? const CircularProgressIndicator()
                    : TextButton(onPressed: load, child: Text('$error，点击重试')))
            : ListView(padding: const EdgeInsets.all(16), children: [
                Wrap(spacing: 8, children: [
                  for (var i = 0; i < current['pages'].length; i++)
                    ChoiceChip(
                        label: Text('第 ${i + 1} 页'),
                        selected: page == i,
                        onSelected: busy
                            ? null
                            : (_) => setState(() {
                                  page = i;
                                  instruction.clear();
                                }))
                ]),
                VisualBlock(
                    visual: Map<String, dynamic>.from(
                        current['pages'][page]['illustration'] as Map)),
                Padding(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    child: Text(current['pages'][page]['text'] as String)),
                Wrap(children: [
                  IconButton(
                      tooltip: '撤销',
                      onPressed: !busy && current['can_undo'] == true
                          ? () => change('undo')
                          : null,
                      icon: const Icon(Icons.undo)),
                  IconButton(
                      tooltip: '重做',
                      onPressed: !busy && current['can_redo'] == true
                          ? () => change('redo')
                          : null,
                      icon: const Icon(Icons.redo)),
                  TextButton(
                      onPressed: busy || current['saved'] == true
                          ? null
                          : () => change('save'),
                      child: Text(
                          current['saved'] == true ? '已保存到我的作品' : '保存到我的作品')),
                ]),
                TextField(
                    controller: instruction,
                    enabled: !busy,
                    decoration: InputDecoration(
                        labelText: '想怎样修改这一页？',
                        suffixIcon: IconButton(
                            tooltip: '提交修改',
                            icon: const Icon(Icons.send),
                            onPressed: busy
                                ? null
                                : () => change('revise', instruction.text)))),
                VoiceComposer(
                    baseUrl: apiBaseUrl,
                    tokens: ref.read(tokenStorageProvider),
                    telemetry: ref.read(telemetryProvider),
                    enabled: !busy,
                    showImageAction: false,
                    holdToTalkText: '按住说出修改',
                    onPickImage: () async {},
                    onVoiceFinal: (text) {
                      instruction.text = text;
                      return change('revise', text);
                    }),
                if (busy) const LinearProgressIndicator(),
                if (error != null) Text(error!),
              ]));
  }
}
