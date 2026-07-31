import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:pretty_qr_code/pretty_qr_code.dart';
import '../core/models.dart';
import '../providers.dart';

class WardListPage extends ConsumerWidget {
  const WardListPage({super.key});
  @override Widget build(BuildContext context, WidgetRef ref) {
    final wards = ref.watch(wardsProvider);
    return Scaffold(appBar: AppBar(title: const Text('被监护者'), actions: [IconButton(onPressed: () => ref.read(authProvider.notifier).logout(), icon: const Icon(Icons.logout))]),
      body: wards.when(loading: () => const Center(child: CircularProgressIndicator()), error: (e, _) => Center(child: Text('加载失败：$e')), data: (items) => items.isEmpty ? const Center(child: Text('还没有档案，点击右下角创建')) : ListView.separated(
        padding: const EdgeInsets.all(16), itemCount: items.length, separatorBuilder: (_, __) => const SizedBox(height: 8), itemBuilder: (_, index) { final ward = items[index]; return Card(child: ListTile(leading: const CircleAvatar(child: Icon(Icons.person)), title: Text(ward.displayName), subtitle: const Text('查看设备与报告'), trailing: const Icon(Icons.chevron_right), onTap: () => context.go('/wards/${ward.id}', extra: ward))); }),
      floatingActionButton: FloatingActionButton.extended(onPressed: () => _create(context, ref), icon: const Icon(Icons.add), label: const Text('新建档案')),
    );
  }
  Future<void> _create(BuildContext context, WidgetRef ref) async {
    final controller = TextEditingController();
    final name = await showDialog<String>(context: context, builder: (context) => AlertDialog(title: const Text('新建档案'), content: TextField(controller: controller, autofocus: true, decoration: const InputDecoration(labelText: '姓名')), actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('取消')), FilledButton(onPressed: () => Navigator.pop(context, controller.text), child: const Text('创建'))]));
    if (name != null && name.trim().isNotEmpty) { await ref.read(apiProvider).createWard(name.trim()); ref.invalidate(wardsProvider); }
  }
}

class WardDetailPage extends ConsumerWidget {
  const WardDetailPage({required this.ward, super.key}); final Ward ward;
  @override Widget build(BuildContext context, WidgetRef ref) {
    final devices = ref.watch(devicesProvider(ward.id));
    return Scaffold(appBar: AppBar(title: Text(ward.displayName)), body: ListView(padding: const EdgeInsets.all(16), children: [
      Text('摄像设备', style: Theme.of(context).textTheme.titleLarge), const SizedBox(height: 8),
      devices.when(loading: () => const LinearProgressIndicator(), error: (e, _) => Text('设备加载失败：$e'), data: (items) => Column(children: items.map((device) => Card(child: ListTile(leading: Icon(device.status == 'online' ? Icons.videocam : Icons.videocam_off), title: Text(device.status == 'online' ? '在线' : '离线'), subtitle: Text(device.lastSeenAt == null ? '尚未绑定' : '最后心跳 ${device.lastSeenAt!.toLocal()}'))).toList())),
      const SizedBox(height: 12), OutlinedButton.icon(onPressed: () => _invite(context, ref), icon: const Icon(Icons.qr_code), label: const Text('添加摄像设备')),
      const SizedBox(height: 28), Text('行为报告', style: Theme.of(context).textTheme.titleLarge), const SizedBox(height: 8), Card(child: ListTile(leading: const Icon(Icons.analytics), title: const Text('今日日报'), subtitle: const Text('分析完成后展示占比与时间轴'), trailing: const Icon(Icons.chevron_right), onTap: () => context.go('/wards/${ward.id}/report', extra: ward))),
    ]));
  }
  Future<void> _invite(BuildContext context, WidgetRef ref) async {
    final invite = await ref.read(apiProvider).invite(ward.id); if (!context.mounted) return;
    await showDialog<void>(context: context, builder: (context) => AlertDialog(title: const Text('用读学Eye 扫码绑定'), content: SizedBox(width: 260, child: Column(mainAxisSize: MainAxisSize.min, children: [PrettyQrView.data(data: invite['qr_payload'], decoration: const PrettyQrDecoration()), const SizedBox(height: 16), SelectableText(invite['invite_code'], style: Theme.of(context).textTheme.headlineMedium), const Text('10 分钟内一次性有效')])), actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('完成'))]));
    ref.invalidate(devicesProvider(ward.id));
  }
}
