import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers.dart';

class WardBindPage extends ConsumerStatefulWidget {
  const WardBindPage({super.key});
  @override
  ConsumerState<WardBindPage> createState() => _WardBindPageState();
}

class _WardBindPageState extends ConsumerState<WardBindPage> {
  final code = TextEditingController(), pin = TextEditingController();
  bool loading = false;
  @override
  Widget build(BuildContext context) => Scaffold(
      appBar: AppBar(title: const Text('学生设备绑定')),
      body: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(children: [
            TextField(
                controller: code,
                decoration: const InputDecoration(labelText: '家长提供的 8 位绑定码')),
            TextField(
                controller: pin,
                keyboardType: TextInputType.number,
                obscureText: true,
                decoration: const InputDecoration(labelText: '设置 4–8 位 PIN')),
            const SizedBox(height: 20),
            FilledButton(
                onPressed: loading ? null : _bind,
                child: Text(loading ? '绑定中…' : '绑定并进入'))
          ])));
  Future<void> _bind() async {
    setState(() => loading = true);
    try {
      final id =
          await ref.read(apiProvider).bindWard(code.text.trim(), pin.text);
      if (mounted) {
        Navigator.of(context).pushReplacement(
            MaterialPageRoute(builder: (_) => WardDayPage(wardId: id)));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('绑定失败，请检查绑定码和 PIN')));
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }
}

class GuardianStoryPage extends ConsumerStatefulWidget {
  const GuardianStoryPage({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<GuardianStoryPage> createState() => _GuardianStoryPageState();
}

class _GuardianStoryPageState extends ConsumerState<GuardianStoryPage> {
  final task = TextEditingController();
  Map<String, dynamic>? story;
  @override
  Widget build(BuildContext context) {
    final s = story;
    return Scaffold(
        appBar: AppBar(title: const Text('今晚的学习故事')),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          TextField(
              controller: task,
              decoration: const InputDecoration(labelText: '交给孩子的作业'),
              onSubmitted: (_) => _add()),
          FilledButton(onPressed: _add, child: const Text('交作业')),
          const SizedBox(height: 16),
          OutlinedButton(onPressed: _invite, child: const Text('生成孩子 App 绑定码')),
          const SizedBox(height: 16),
          FilledButton.tonal(onPressed: _load, child: const Text('查看当晚事实报告')),
          if (s != null)
            Card(
                child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: s['status'] == 'locked'
                        ? const Text('孩子完成自评后，今晚报告会在这里出现。')
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                                Text(
                                    '学习用时：${(s['total_seconds'] as int) ~/ 60} 分钟'),
                                Text('答疑卡点：${s['stuck_points']} 个'),
                                const Text('沟通建议',
                                    style:
                                        TextStyle(fontWeight: FontWeight.bold)),
                                ...((s['communication_suggestions'] as List)
                                    .map((x) => Text('• $x')))
                              ])))
        ]));
  }

  Future<void> _add() async {
    if (task.text.trim().isEmpty) return;
    await ref
        .read(apiProvider)
        .createAssignment(widget.wardId, task.text.trim());
    task.clear();
  }

  Future<void> _invite() async {
    final x = await ref.read(apiProvider).wardInvite(widget.wardId);
    if (mounted) {
      showDialog(
          context: context,
          builder: (_) => AlertDialog(
                  title: const Text('孩子 App 绑定码'),
                  content: SelectableText(x['invite_code']),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: const Text('完成'))
                  ]));
    }
  }

  Future<void> _load() async {
    final x = await ref
        .read(apiProvider)
        .guardianStory(widget.wardId, DateTime.now());
    if (mounted) setState(() => story = x);
  }
}

class WardDayPage extends ConsumerStatefulWidget {
  const WardDayPage({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<WardDayPage> createState() => _WardDayPageState();
}

class _WardDayPageState extends ConsumerState<WardDayPage> {
  List<dynamic> tasks = [];
  Map<String, dynamic>? plan, insight;
  String? session, answer;
  final watch = Stopwatch();
  Timer? timer;
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = plan;
    final children = <Widget>[];
    if (p == null) {
      children.add(const Text('先选出今天要做的任务'));
      children.addAll(tasks.map((x) => ListTile(
          leading: const Icon(Icons.assignment),
          title: Text(x['title'] as String))));
      children.add(FilledButton(
          onPressed: tasks.isEmpty ? null : _plan,
          child: const Text('生成并确认今日计划')));
    } else {
      children.add(Text(p['status'] == 'confirmed' ? '计划已确认' : '计划草稿'));
      children.addAll((p['items'] as List).map((x) => Card(
          child: ListTile(
              title: Text(x['title']),
              trailing: FilledButton(
                  onPressed: () => _start(x['id']),
                  child: const Text('开始'))))));
      if (session != null) {
        children.add(_Companion(
            seconds: watch.elapsed.inSeconds,
            answer: answer,
            onAsk: _ask,
            onFinish: _finish));
      }
      children.add(OutlinedButton(
          onPressed: _review, child: const Text('完成今天学习，做 30 秒自评')));
      if (insight != null) {
        children.add(Card(
            child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                    '锦囊：${insight!['advice']}\nAI 行为记录：${insight!['objective_timeline']}'))));
      }
    }
    return Scaffold(
        appBar: AppBar(title: const Text('我的今日计划')),
        body: ListView(padding: const EdgeInsets.all(16), children: children));
  }

  Future<void> _load() async {
    tasks = await ref.read(apiProvider).assignments(widget.wardId);
    if (mounted) setState(() {});
  }

  Future<void> _plan() async {
    final day = DateTime.now();
    await ref.read(apiProvider).savePlan(
        widget.wardId,
        day,
        tasks
            .map((x) => {
                  'assignment_id': x['id'],
                  'title': x['title'],
                  'planned_minutes': 30
                })
            .toList());
    await ref.read(apiProvider).confirmPlan(widget.wardId, day);
    plan = await ref.read(apiProvider).plan(widget.wardId, day);
    if (mounted) setState(() {});
  }

  Future<void> _start(String id) async {
    session = (await ref.read(apiProvider).startSession(id))['id'] as String;
    watch
      ..reset()
      ..start();
    timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
    setState(() {});
  }

  Future<void> _ask(String text) async {
    answer = await ref.read(apiProvider).ask(session!, text);
    if (mounted) setState(() {});
  }

  Future<void> _finish() async {
    watch.stop();
    await ref
        .read(apiProvider)
        .finishSession(session!, watch.elapsed.inSeconds);
    timer?.cancel();
    session = null;
    if (mounted) setState(() {});
  }

  Future<void> _review() async {
    await ref.read(apiProvider).review(widget.wardId, DateTime.now(), '顺利');
    insight =
        await ref.read(apiProvider).insight(widget.wardId, DateTime.now());
    if (mounted) setState(() {});
  }
}

class _Companion extends StatefulWidget {
  const _Companion(
      {required this.seconds,
      required this.answer,
      required this.onAsk,
      required this.onFinish});
  final int seconds;
  final String? answer;
  final Future<void> Function(String) onAsk;
  final VoidCallback onFinish;
  @override
  State<_Companion> createState() => _CompanionState();
}

class _CompanionState extends State<_Companion> {
  final input = TextEditingController();
  @override
  Widget build(BuildContext context) => Card(
      child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(children: [
            Text('专注 ${widget.seconds ~/ 60} 分钟'),
            TextField(
                controller: input,
                decoration: const InputDecoration(labelText: '卡住了？问问 AI 伙伴'),
                onSubmitted: widget.onAsk),
            if (widget.answer != null) Text(widget.answer!),
            TextButton(onPressed: widget.onFinish, child: const Text('完成任务'))
          ])));
}
