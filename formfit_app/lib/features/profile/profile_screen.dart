import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../models/user.dart';
import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  late TextEditingController _age, _height, _weight, _days, _injury;
  String? _gender, _goal, _level;
  late List<String> _equipment;
  late List<String> _contra;
  bool _saving = false;

  static const _goals = ['增肌', '减脂', '塑形', '维持', '康复'];
  static const _levels = [
    ('beginner', '新手'),
    ('intermediate', '进阶'),
    ('advanced', '高阶'),
  ];
  static const _equipments = [
    ('body weight', '自重'),
    ('dumbbell', '哑铃'),
    ('barbell', '杠铃'),
    ('cable', '龙门架'),
    ('kettlebell', '壶铃'),
    ('band', '弹力带'),
    ('leverage machine', '固定器械'),
    ('stability ball', '瑜伽球'),
  ];
  static const _bodyParts = ['膝盖', '腰', '肩', '颈', '肘', '腕'];

  @override
  void initState() {
    super.initState();
    final p = ref.read(authProvider).profile ?? UserProfile();
    _age = TextEditingController(text: p.age?.toString() ?? '');
    _height = TextEditingController(text: p.heightCm?.toStringAsFixed(0) ?? '');
    _weight = TextEditingController(text: p.weightKg?.toStringAsFixed(0) ?? '');
    _days = TextEditingController(text: (p.daysPerWeek ?? 3).toString());
    _injury = TextEditingController(text: p.injuryNotes ?? '');
    _gender = p.gender;
    _goal = p.goal;
    _level = p.level;
    _equipment = List.of(p.availableEquipment);
    _contra = List.of(p.contraindicatedParts);
  }

  @override
  void dispose() {
    _age.dispose();
    _height.dispose();
    _weight.dispose();
    _days.dispose();
    _injury.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _saving = true);
    final profile = UserProfile(
      gender: _gender,
      age: int.tryParse(_age.text),
      heightCm: double.tryParse(_height.text),
      weightKg: double.tryParse(_weight.text),
      goal: _goal,
      level: _level,
      daysPerWeek: int.tryParse(_days.text),
      availableEquipment: _equipment,
      injuryNotes: _injury.text.trim().isEmpty ? null : _injury.text.trim(),
      contraindicatedParts: _contra,
    );
    try {
      await ref.read(authProvider.notifier).saveProfile(profile);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('档案已保存'), backgroundColor: AppColors.success),
        );
        context.pop();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('保存失败：$e'), backgroundColor: AppColors.danger),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('身体档案')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            _sectionTitle('基本信息'),
            _genderSelector(),
            const SizedBox(height: 16),
            Row(children: [
              Expanded(child: _numField(_age, '年龄', '岁')),
              const SizedBox(width: 12),
              Expanded(child: _numField(_days, '每周训练', '天', max: 7)),
            ]),
            const SizedBox(height: 16),
            Row(children: [
              Expanded(child: _numField(_height, '身高', 'cm')),
              const SizedBox(width: 12),
              Expanded(child: _numField(_weight, '体重', 'kg')),
            ]),
            const SizedBox(height: 28),

            _sectionTitle('训练目标'),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: _goals.map((g) {
                final selected = _goal == g;
                return ChoiceChip(
                  label: Text(g),
                  selected: selected,
                  onSelected: (_) => setState(() => _goal = g),
                  selectedColor: AppColors.primary.withValues(alpha: .15),
                  labelStyle: TextStyle(
                    color: selected ? AppColors.primary : AppColors.textPrimary,
                    fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                  ),
                  showCheckmark: false,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                    side: BorderSide(
                      color: selected ? AppColors.primary : const Color(0xFFE5E7EB),
                    ),
                  ),
                );
              }).toList(),
            ),
            const SizedBox(height: 20),

            _sectionTitle('训练水平'),
            Wrap(
              spacing: 10,
              children: _levels.map((l) {
                final selected = _level == l.$1;
                return ChoiceChip(
                  label: Text(l.$2),
                  selected: selected,
                  onSelected: (_) => setState(() => _level = l.$1),
                  selectedColor: AppColors.primary.withValues(alpha: .15),
                  labelStyle: TextStyle(
                    color: selected ? AppColors.primary : AppColors.textPrimary,
                    fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                  ),
                  showCheckmark: false,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                    side: BorderSide(
                      color: selected ? AppColors.primary : const Color(0xFFE5E7EB),
                    ),
                  ),
                );
              }).toList(),
            ),
            const SizedBox(height: 28),

            _sectionTitle('可用器械', sub: '已选 ${_equipment.length} 项'),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: _equipments.map((e) {
                final selected = _equipment.contains(e.$1);
                return FilterChip(
                  label: Text(e.$2),
                  selected: selected,
                  onSelected: (v) => setState(() {
                    if (v) {
                      _equipment.add(e.$1);
                    } else {
                      _equipment.remove(e.$1);
                    }
                  }),
                  selectedColor: AppColors.primary.withValues(alpha: .15),
                  checkmarkColor: AppColors.primary,
                  labelStyle: TextStyle(
                    color: selected ? AppColors.primary : AppColors.textPrimary,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                    side: BorderSide(
                      color: selected ? AppColors.primary : const Color(0xFFE5E7EB),
                    ),
                  ),
                );
              }).toList(),
            ),
            const SizedBox(height: 28),

            _sectionTitle('伤病史 / 禁忌部位'),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: _bodyParts.map((p) {
                final selected = _contra.contains(p);
                return FilterChip(
                  label: Text(p),
                  selected: selected,
                  onSelected: (v) => setState(() {
                    if (v) {
                      _contra.add(p);
                    } else {
                      _contra.remove(p);
                    }
                  }),
                  selectedColor: AppColors.warning.withValues(alpha: .15),
                  checkmarkColor: AppColors.warning,
                  labelStyle: TextStyle(
                    color: selected ? AppColors.warning : AppColors.textPrimary,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(AppRadius.pill),
                    side: BorderSide(
                      color: selected ? AppColors.warning : const Color(0xFFE5E7EB),
                    ),
                  ),
                );
              }).toList(),
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _injury,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: '补充说明（选填）',
                hintText: '如：左肩活动受限、腰椎间盘突出等',
                alignLabelWithHint: true,
              ),
            ),
            const SizedBox(height: 36),

            ElevatedButton(
              onPressed: _saving ? null : _save,
              child: _saving
                  ? const SizedBox(
                      width: 22, height: 22,
                      child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white))
                  : const Text('保存档案'),
            ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  Widget _sectionTitle(String text, {String? sub}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        children: [
          Text(text,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
          if (sub != null) ...[
            const SizedBox(width: 8),
            Text(sub,
                style: const TextStyle(color: AppColors.textSecondary, fontSize: 12)),
          ],
        ],
      ),
    );
  }

  Widget _genderSelector() {
    return Row(
      children: [
        Expanded(child: _genderOption('male', Icons.male, '男')),
        const SizedBox(width: 12),
        Expanded(child: _genderOption('female', Icons.female, '女')),
      ],
    );
  }

  Widget _genderOption(String value, IconData icon, String label) {
    final selected = _gender == value;
    return GestureDetector(
      onTap: () => setState(() => _gender = value),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14),
        decoration: BoxDecoration(
          color: selected ? AppColors.primary.withValues(alpha: .1) : null,
          borderRadius: BorderRadius.circular(AppRadius.sm),
          border: Border.all(
            color: selected ? AppColors.primary : const Color(0xFFE5E7EB),
            width: selected ? 1.5 : 1,
          ),
        ),
        child: Column(
          children: [
            Icon(icon,
                color: selected ? AppColors.primary : AppColors.textSecondary),
            const SizedBox(height: 4),
            Text(label,
                style: TextStyle(
                    color: selected ? AppColors.primary : AppColors.textPrimary,
                    fontWeight: selected ? FontWeight.w700 : FontWeight.w400)),
          ],
        ),
      ),
    );
  }

  Widget _numField(TextEditingController c, String label, String unit,
      {int max = 99}) {
    return TextFormField(
      controller: c,
      keyboardType: TextInputType.number,
      decoration: InputDecoration(
        labelText: label,
        suffixText: unit,
      ),
      validator: (v) {
        if (v == null || v.isEmpty) return null;
        final n = int.tryParse(v);
        if (n == null || n <= 0 || n > max) return '请输入有效数字';
        return null;
      },
    );
  }
}
