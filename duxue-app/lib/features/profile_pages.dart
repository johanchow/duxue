import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/models.dart';
import '../providers.dart';

const _fields = <String, String>{
  'hand_action': '手部动作',
  'desk_objects': '桌面物品',
  'head_orientation': '头部朝向',
  'body_pos': '身体姿态',
  'seat_status': '在座状态',
  'motion_state': '运动状态',
};

class ProfileListPage extends ConsumerWidget {
  const ProfileListPage({required this.wardId, super.key});
  final String wardId;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profiles = ref.watch(profilesProvider);
    final wards = ref.watch(wardsProvider).valueOrNull ?? const <Ward>[];
    final selected = wards.where((ward) => ward.id == wardId);
    final profileId =
        selected.isEmpty ? null : selected.first.analysisProfileId;
    return Scaffold(
      appBar: AppBar(title: const Text('分析配置')),
      body: profiles.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(child: Text('加载失败：$error')),
        data: (items) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text('为档案选择一套分析规则。切换后历史报告会标记为基于旧配置生成。'),
            const SizedBox(height: 12),
            Card(
              child: RadioListTile<String?>(
                value: null,
                groupValue: profileId,
                title: const Text('系统默认规则'),
                subtitle: const Text('学习、走神/玩耍、离开'),
                onChanged: (_) => _assign(ref, null),
              ),
            ),
            ...items.map(
              (profile) => Card(
                child: RadioListTile<String?>(
                  value: profile.id,
                  groupValue: profileId,
                  title: Text(profile.name),
                  subtitle: Text(
                    profile.extraObservationPrompt.isEmpty
                        ? '未添加额外观察提示'
                        : profile.extraObservationPrompt,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  secondary: IconButton(
                    icon: const Icon(Icons.edit_outlined),
                    tooltip: '编辑',
                    onPressed: () => Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => ProfileEditPage(profileId: profile.id),
                      ),
                    ),
                  ),
                  onChanged: (_) => _assign(ref, profile.id),
                ),
              ),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => const ProfileEditPage()),
              ),
              icon: const Icon(Icons.add),
              label: const Text('新建分析配置'),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _assign(WidgetRef ref, String? profileId) async {
    await ref
        .read(apiProvider)
        .updateWard(wardId, analysisProfileId: profileId);
    ref.invalidate(wardsProvider);
  }
}

class ProfileEditPage extends ConsumerStatefulWidget {
  const ProfileEditPage({this.profileId, super.key});
  final String? profileId;
  @override
  ConsumerState<ProfileEditPage> createState() => _ProfileEditPageState();
}

class _ProfileEditPageState extends ConsumerState<ProfileEditPage> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _prompt = TextEditingController();
  bool _initialized = false;
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    _prompt.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final detail = widget.profileId == null
        ? null
        : ref.watch(profileProvider(widget.profileId!));
    if (detail != null && !_initialized && detail.hasValue) {
      _initialized = true;
      _name.text = detail.requireValue.name;
      _prompt.text = detail.requireValue.extraObservationPrompt;
    }
    if (detail != null && detail.isLoading && !_initialized) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (detail != null && detail.hasError) {
      return Scaffold(
        appBar: AppBar(),
        body: Center(child: Text('加载失败：${detail.error}')),
      );
    }
    final profile = detail?.valueOrNull;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.profileId == null ? '新建分析配置' : '编辑分析配置'),
        actions: [
          if (profile != null)
            IconButton(
              icon: const Icon(Icons.delete_outline),
              tooltip: '删除',
              onPressed: () => _delete(profile),
            ),
        ],
      ),
      body: Form(
        key: _form,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            TextFormField(
              controller: _name,
              decoration: const InputDecoration(
                labelText: '配置名称',
                hintText: '例如：晚间作业',
              ),
              validator: (value) =>
                  value == null || value.trim().isEmpty ? '请输入配置名称' : null,
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _prompt,
              minLines: 3,
              maxLines: 5,
              decoration: const InputDecoration(
                labelText: '额外观察提示（可选）',
                hintText: '例如：特别留意是否频繁离开座位',
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _saving ? null : _saveProfile,
              child: Text(_saving ? '保存中…' : '保存配置'),
            ),
            if (profile != null) ...[
              const SizedBox(height: 28),
              Text('自定义行为标签', style: Theme.of(context).textTheme.titleLarge),
              const Padding(
                padding: EdgeInsets.only(top: 6, bottom: 8),
                child: Text('参考短语应描述摄像头可观察到的动作或物品。优先级更高的标签会优先匹配。'),
              ),
              if (profile.labels.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(16),
                    child: Text('尚无自定义标签'),
                  ),
                ),
              ...profile.labels.map(
                (label) => Card(
                  child: ListTile(
                    title: Text(label.name),
                    subtitle: Text(
                      '${label.isActive ? '已启用' : '已停用'} · 优先级 ${label.priority} · ${label.fieldPrototypes.values.fold<int>(0, (count, items) => count + items.length)} 条参考短语',
                    ),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => _editLabel(profile, label),
                  ),
                ),
              ),
              OutlinedButton.icon(
                onPressed: () => _editLabel(profile, null),
                icon: const Icon(Icons.add),
                label: const Text('添加行为标签'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _saveProfile() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _saving = true);
    try {
      final api = ref.read(apiProvider);
      final profile = widget.profileId == null
          ? await api.createProfile(
              name: _name.text.trim(),
              prompt: _prompt.text.trim(),
            )
          : await api.updateProfile(
              widget.profileId!,
              name: _name.text.trim(),
              prompt: _prompt.text.trim(),
            );
      ref.invalidate(profilesProvider);
      ref.invalidate(profileProvider(profile.id));
      if (mounted && widget.profileId == null) {
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(
            builder: (_) => ProfileEditPage(profileId: profile.id),
          ),
        );
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('保存失败：$error')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete(AnalysisProfile profile) async {
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除分析配置？'),
        content: const Text('已绑定到档案的配置不能删除。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (approved != true) return;
    try {
      await ref.read(apiProvider).deleteProfile(profile.id);
      ref.invalidate(profilesProvider);
      if (mounted) {
        Navigator.pop(context);
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('删除失败：$error')));
      }
    }
  }

  Future<void> _editLabel(AnalysisProfile profile, BehaviorLabel? label) async {
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => LabelEditor(profileId: profile.id, label: label),
    );
    if (changed == true) ref.invalidate(profileProvider(profile.id));
  }
}

class LabelEditor extends ConsumerStatefulWidget {
  const LabelEditor({required this.profileId, this.label, super.key});
  final String profileId;
  final BehaviorLabel? label;
  @override
  ConsumerState<LabelEditor> createState() => _LabelEditorState();
}

class _LabelEditorState extends ConsumerState<LabelEditor> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _name = TextEditingController(
    text: widget.label?.name ?? '',
  );
  late final TextEditingController _priority = TextEditingController(
    text: '${widget.label?.priority ?? 0}',
  );
  late bool _active = widget.label?.isActive ?? true;
  late final List<_PrototypeRow> _rows = widget.label?.fieldPrototypes.entries
          .expand(
            (entry) => entry.value.map(
              (text) => _PrototypeRow(field: entry.key, text: text),
            ),
          )
          .toList() ??
      [];
  bool _saving = false;
  @override
  void dispose() {
    _name.dispose();
    _priority.dispose();
    for (final row in _rows) {
      row.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: EdgeInsets.fromLTRB(
            16,
            16,
            16,
            16 + MediaQuery.viewInsetsOf(context).bottom,
          ),
          child: Form(
            key: _form,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    widget.label == null ? '添加行为标签' : '编辑行为标签',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _name,
                    decoration: const InputDecoration(
                      labelText: '标签名称',
                      hintText: '例如：咬手指',
                    ),
                    validator: (value) => value == null || value.trim().isEmpty
                        ? '请输入标签名称'
                        : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _priority,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: '优先级',
                      helperText: '数值越大，匹配时优先级越高',
                    ),
                    validator: (value) =>
                        int.tryParse(value ?? '') == null ? '请输入整数' : null,
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('启用此标签'),
                    value: _active,
                    onChanged: (value) => setState(() => _active = value),
                  ),
                  const SizedBox(height: 8),
                  Text('参考短语', style: Theme.of(context).textTheme.titleMedium),
                  const Text('选择字段后，写下摄像头画面中可观察到的典型描述。'),
                  const SizedBox(height: 8),
                  ..._rows.asMap().entries.map(
                        (entry) => _prototypeInput(entry.key, entry.value),
                      ),
                  OutlinedButton.icon(
                    onPressed: () => setState(
                      () => _rows.add(_PrototypeRow(field: _fields.keys.first)),
                    ),
                    icon: const Icon(Icons.add),
                    label: const Text('添加参考短语'),
                  ),
                  const SizedBox(height: 16),
                  FilledButton(
                    onPressed: _saving ? null : _save,
                    child: Text(_saving ? '保存中…' : '保存标签'),
                  ),
                  if (widget.label != null)
                    TextButton.icon(
                      onPressed: _delete,
                      icon: const Icon(Icons.delete_outline),
                      label: const Text('删除此标签'),
                    ),
                ],
              ),
            ),
          ),
        ),
      );

  Widget _prototypeInput(int index, _PrototypeRow row) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 126,
              child: DropdownButtonFormField<String>(
                value: _fields.containsKey(row.field)
                    ? row.field
                    : _fields.keys.first,
                isExpanded: true,
                decoration: const InputDecoration(labelText: '观察字段'),
                items: _fields.entries
                    .map(
                      (item) => DropdownMenuItem(
                        value: item.key,
                        child: Text(item.value),
                      ),
                    )
                    .toList(),
                onChanged: (value) => setState(() => row.field = value!),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextFormField(
                controller: row.controller,
                decoration: const InputDecoration(
                  labelText: '参考短语',
                  hintText: '例如：右手手指放在嘴边',
                ),
                validator: (value) =>
                    value == null || value.trim().isEmpty ? '请输入短语' : null,
              ),
            ),
            IconButton(
              onPressed: () => setState(() {
                final removed = _rows.removeAt(index);
                removed.dispose();
              }),
              icon: const Icon(Icons.remove_circle_outline),
              tooltip: '删除',
            ),
          ],
        ),
      );

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    final prototypes = <String, List<String>>{};
    for (final row in _rows) {
      prototypes
          .putIfAbsent(row.field, () => [])
          .add(row.controller.text.trim());
    }
    setState(() => _saving = true);
    try {
      await ref.read(apiProvider).saveLabel(
            widget.profileId,
            labelId: widget.label?.id,
            name: _name.text.trim(),
            prototypes: prototypes,
            priority: int.parse(_priority.text),
            isActive: _active,
          );
      if (mounted) {
        Navigator.pop(context, true);
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('保存失败：$error')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete() async {
    try {
      await ref
          .read(apiProvider)
          .deleteLabel(widget.profileId, widget.label!.id);
      if (mounted) {
        Navigator.pop(context, true);
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('删除失败：$error')));
      }
    }
  }
}

class _PrototypeRow {
  _PrototypeRow({required this.field, String text = ''})
      : controller = TextEditingController(text: text);
  String field;
  final TextEditingController controller;
  void dispose() => controller.dispose();
}
