import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers.dart';
import '../shared/app_ui.dart';

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
  int tab = 0;
  bool observing = true;
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
    return Scaffold(
      appBar: AppBar(title: Text(['今晚的计划', 'AI 伙伴', '成长'][tab])),
      body: switch (tab) {
        0 => _home(context),
        1 => _ai(context),
        _ => _growth(context)
      },
      bottomNavigationBar: NavigationBar(
          selectedIndex: tab,
          onDestinationSelected: (value) => setState(() => tab = value),
          destinations: const [
            NavigationDestination(
                icon: Icon(Icons.home_outlined),
                selectedIcon: Icon(Icons.home),
                label: '首页'),
            NavigationDestination(
                icon: Icon(Icons.chat_bubble_outline),
                selectedIcon: Icon(Icons.chat_bubble),
                label: 'AI 伙伴'),
            NavigationDestination(
                icon: Icon(Icons.eco_outlined),
                selectedIcon: Icon(Icons.eco),
                label: '成长')
          ]),
    );
  }

  Widget _home(BuildContext context) {
    final p = plan;
    final children = <Widget>[];
    children.add(Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: StatusPill(
            text: observing ? '学习观察中 · 仅记录，不显示实时专注判断' : '学习观察已暂停',
            color: observing ? brandBlue : Colors.orange)));
    if (p == null) {
      children.add(const Text('这是系统目前知道的任务。你可以补充、调整，再决定今天怎么安排。',
          style: TextStyle(color: Colors.blueGrey)));
      children.addAll(tasks.map((x) => Padding(
          padding: const EdgeInsets.only(top: 8),
          child: AppCard(
              child: ListTile(
                  leading: const Icon(Icons.assignment_outlined),
                  title: Text(x['title'] as String),
                  subtitle: const Text('待安排'))))));
      children.add(const SizedBox(height: 12));
      children.add(FilledButton(
          onPressed: tasks.isEmpty ? null : _plan,
          child: const Text('确认我的今日计划')));
    } else {
      children.add(Text(p['status'] == 'confirmed' ? '这是你确认的计划' : '计划草稿',
          style: Theme.of(context).textTheme.titleMedium));
      children.addAll(
        (p['items'] as List).map(
          (x) => Padding(
            padding: const EdgeInsets.only(top: 8),
            child: AppCard(
              child: ListTile(
                title: Text(x['title']),
                subtitle: const Text('按自己的节奏来'),
                trailing: FilledButton(
                  onPressed: () => _start(x['id']),
                  child: const Text('开始'),
                ),
              ),
            ),
          ),
        ),
      );
      children.add(const SizedBox(height: 12));
      children.add(OutlinedButton.icon(
          onPressed: _showObserveControls,
          icon: const Icon(Icons.visibility_outlined),
          label: Text(session == null
              ? '查看学习观察状态'
              : '学习观察中 · ${watch.elapsed.inSeconds ~/ 60} 分钟')));
      children.add(const SizedBox(height: 8));
      children.add(FilledButton.tonal(
          onPressed: _review, child: const Text('完成今日计划，先说说自己的感受')));
    }
    return ListView(padding: const EdgeInsets.all(16), children: children);
  }

  Widget _ai(BuildContext context) =>
      ListView(padding: const EdgeInsets.all(16), children: [
        const Text('学习卡壳时随时问，我会一步步陪你想明白。',
            style: TextStyle(color: Colors.blueGrey)),
        const SizedBox(height: 14),
        if (session == null)
          const AppCard(
              child: Padding(
                  padding: EdgeInsets.all(20),
                  child: Text('先从首页开始一个计划任务，再来和 AI 伙伴一起解决问题。')))
        else
          _Companion(
              seconds: watch.elapsed.inSeconds,
              answer: answer,
              onAsk: _ask,
              onFinish: _finish)
      ]);

  Widget _growth(BuildContext context) =>
      ListView(padding: const EdgeInsets.all(16), children: [
        const SectionLabel('今天'),
        if (insight == null)
          const AppCard(
              child: ListTile(
                  leading: Icon(Icons.edit_note),
                  title: Text('今天的反馈等待生成'),
                  subtitle: Text('完成今天的自我总结后，这里会出现你的感受和观察记录的对照。')))
        else
          AppCard(
              child: Padding(
                  padding: const EdgeInsets.all(4),
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const ListTile(
                            leading: Icon(Icons.compare_arrows),
                            title: Text('你的感受与观察记录'),
                            subtitle: Text('先看自己的体感，再一起发现学习节奏。')),
                        Padding(
                            padding: const EdgeInsets.all(12),
                            child: Text('给你的小建议：${insight!['advice']}')),
                        Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 12),
                            child:
                                Text('观察记录：${insight!['objective_timeline']}'))
                      ]))),
        const SectionLabel('过去的成长'),
        const AppCard(
            child: ListTile(
                leading: Icon(Icons.history),
                title: Text('历史总结与反馈'),
                subtitle: Text('过去的成长信息始终可以查看'))),
      ]);

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
    observing = true;
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
    try {
      await ref.read(apiProvider).review(widget.wardId, DateTime.now(), '顺利');
      insight =
          await ref.read(apiProvider).insight(widget.wardId, DateTime.now());
      if (mounted) setState(() => tab = 2);
    } catch (e) {
      if (mounted) showMessage(context, '提交自我总结失败：$e');
    }
  }

  void _showObserveControls() => showModalBottomSheet<void>(
        context: context,
        builder: (context) => Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('学习观察',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Text(session == null
                  ? '当前未开始记录。开始任务后，设备会安静记录学习过程。'
                  : '${observing ? '正在记录' : '记录已暂停'} · 关联当前学习任务 · 已记录 ${watch.elapsed.inSeconds ~/ 60} 分钟'),
              const SizedBox(height: 12),
              const Text('这里不会显示实时专注或分心判断。'),
              const SizedBox(height: 12),
              Row(children: [
                OutlinedButton(
                    onPressed: () {
                      setState(() => observing = !observing);
                      Navigator.pop(context);
                    },
                    child: Text(observing ? '暂停记录' : '继续记录')),
                const SizedBox(width: 8),
                if (session != null)
                  TextButton(
                      onPressed: () async {
                        Navigator.pop(context);
                        await _finish();
                      },
                      child: const Text('结束记录')),
              ]),
            ],
          ),
        ),
      );
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
