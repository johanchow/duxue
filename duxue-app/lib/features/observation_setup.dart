import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/models.dart';
import '../providers.dart';

class ObservationSetup extends ConsumerStatefulWidget {
  const ObservationSetup({required this.wardId, super.key});
  final String wardId;
  @override
  ConsumerState<ObservationSetup> createState() => _ObservationSetupState();
}

class _ObservationSetupState extends ConsumerState<ObservationSetup> {
  bool loading = true,
      saving = false,
      enabled = false,
      reports = false,
      loaded = false;
  String? camera, error;
  TimeOfDay deadline = const TimeOfDay(hour: 21, minute: 30);
  List<Device> devices = [];
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final api = ref.read(apiProvider);
      final list = await api.devices(widget.wardId);
      final response =
          await api.dio.get('/wards/${widget.wardId}/observation-settings');
      if (!mounted) return;
      final data = response.data;
      final clock = (data['deadline'] as String).split(':');
      setState(() {
        devices = list;
        camera = data['camera_id'] as String? ??
            (list.length == 1 ? list.first.id : null);
        enabled = data['enabled'] == true;
        reports = data['report_enabled'] == true;
        deadline =
            TimeOfDay(hour: int.parse(clock[0]), minute: int.parse(clock[1]));
        loading = false;
        loaded = true;
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          loading = false;
          error = '设置读取失败，请重试';
        });
      }
    }
  }

  Future<void> _save() async {
    setState(() => saving = true);
    try {
      await ref
          .read(apiProvider)
          .dio
          .put('/wards/${widget.wardId}/observation-settings', data: {
        'enabled': enabled,
        'camera_id': camera,
        'report_enabled': reports,
        'deadline':
            '${deadline.hour.toString().padLeft(2, '0')}:${deadline.minute.toString().padLeft(2, '0')}',
      });
      if (mounted) Navigator.pop(context);
    } catch (_) {
      if (mounted) {
        setState(() {
          saving = false;
          error = '设置未保存，请检查设备后重试';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => SafeArea(
      child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text('学习观察', style: Theme.of(context).textTheme.titleLarge),
            if (loading)
              const CircularProgressIndicator()
            else ...[
              if (devices.isEmpty) const Text('请先接入摄像设备'),
              if (devices.isNotEmpty)
                DropdownButton<String>(
                    value: devices.any((d) => d.id == camera) ? camera : null,
                    hint: const Text('选择摄像设备'),
                    items: [
                      for (var i = 0; i < devices.length; i++)
                        DropdownMenuItem(
                            value: devices[i].id,
                            child: Text(
                                '摄像设备 ${i + 1} · ${devices[i].status == 'online' ? '在线' : '离线'}')),
                    ],
                    onChanged: (value) => setState(() => camera = value)),
              SwitchListTile(
                  title: const Text('分析学习活动'),
                  value: enabled,
                  onChanged: devices.isEmpty
                      ? null
                      : (value) => setState(() => enabled = value)),
              SwitchListTile(
                  title: const Text('自动生成晚间报告'),
                  value: reports,
                  onChanged: (value) => setState(() => reports = value)),
              ListTile(
                  title: const Text('晚间报告时间'),
                  trailing: Text(deadline.format(context)),
                  onTap: () async {
                    final value = await showTimePicker(
                        context: context, initialTime: deadline);
                    if (mounted && value != null) {
                      setState(() => deadline = value);
                    }
                  }),
              if (error != null) Text(error!),
              FilledButton(
                  onPressed: saving || !loaded ? null : _save,
                  child: Text(saving ? '保存中…' : '保存')),
            ],
          ])));
}
