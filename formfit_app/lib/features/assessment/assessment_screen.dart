import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../api/repository.dart';
import '../../models/assessment.dart';
import '../../providers/auth_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/badges.dart';

class AssessmentScreen extends ConsumerStatefulWidget {
  const AssessmentScreen({super.key});

  @override
  ConsumerState<AssessmentScreen> createState() => _AssessmentScreenState();
}

class _AssessmentScreenState extends ConsumerState<AssessmentScreen> {
  File? _image;
  bool _analyzing = false;
  Assessment? _result;
  String? _error;

  Future<void> _pick(ImageSource source) async {
    final picker = ImagePicker();
    final x = await picker.pickImage(
      source: source,
      maxWidth: 1280,
      imageQuality: 85,
    );
    if (x == null) return;
    setState(() {
      _image = File(x.path);
      _result = null;
      _error = null;
    });
  }

  Future<void> _analyze() async {
    if (_image == null) return;
    final profile = ref.read(authProvider).profile;
    setState(() {
      _analyzing = true;
      _error = null;
    });
    try {
      final result = await ref.read(apiRepositoryProvider).assess(
            image: _image!,
            heightCm: profile?.heightCm,
            weightKg: profile?.weightKg,
            age: profile?.age,
            gender: profile?.gender,
          );
      setState(() => _result = result);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _analyzing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('体态评估')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _introCard(),
            const SizedBox(height: 20),
            _imagePicker(),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!,
                  style: const TextStyle(color: AppColors.danger, fontSize: 13)),
            ],
            const SizedBox(height: 20),
            if (_result != null) _resultCard(_result!),
            if (_result == null && _image != null && !_analyzing)
              ElevatedButton.icon(
                onPressed: _analyze,
                icon: const Icon(Icons.auto_awesome, color: Colors.black),
                label: const Text('开始 AI 评估',
                    style: TextStyle(color: Colors.black)),
              ),
            if (_analyzing) _analyzingCard(),
          ],
        ),
      ),
    );
  }

  Widget _introCard() {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFF0E1114), Color(0xFF1F2A30)],
          begin: Alignment.topLeft,
        ),
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AppColors.primary.withValues(alpha: .15),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Icon(Icons.camera_alt_rounded,
                color: AppColors.primary, size: 24),
          ),
          const SizedBox(width: 14),
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('AI 体态分析',
                    style: TextStyle(
                        color: Colors.white,
                        fontSize: 16,
                        fontWeight: FontWeight.w700)),
                SizedBox(height: 4),
                Text('上传全身照，AI 给出增肌/减脂/康复方向建议',
                    style: TextStyle(color: Colors.white60, fontSize: 12)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _imagePicker() {
    return GestureDetector(
      onTap: _analyzing ? null : () => _showSourceSheet(),
      child: Container(
        height: 280,
        decoration: BoxDecoration(
          color: Theme.of(context).cardColor,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(
            color: AppColors.primary.withValues(alpha: .4),
            width: 1.5,
            style: BorderStyle.solid,
          ),
        ),
        clipBehavior: Clip.antiAlias,
        child: _image != null
            ? Stack(
                fit: StackFit.expand,
                children: [
                  Image.file(_image!, fit: BoxFit.cover),
                  Positioned(
                    right: 10,
                    top: 10,
                    child: CircleAvatar(
                      radius: 16,
                      backgroundColor: Colors.black54,
                      child: IconButton(
                        iconSize: 16,
                        padding: EdgeInsets.zero,
                        icon: const Icon(Icons.close, color: Colors.white),
                        onPressed: () => setState(() {
                          _image = null;
                          _result = null;
                        }),
                      ),
                    ),
                  ),
                ],
              )
            : Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: AppColors.primary.withValues(alpha: .1),
                    ),
                    child: const Icon(Icons.add_a_photo_outlined,
                        size: 36, color: AppColors.primary),
                  ),
                  const SizedBox(height: 14),
                  const Text('点击拍照或选择照片',
                      style: TextStyle(
                          fontSize: 15, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  const Text('建议全身正面照、光线充足',
                      style: TextStyle(
                          color: AppColors.textSecondary, fontSize: 12)),
                ],
              ),
      ),
    );
  }

  Widget _analyzingCard() {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.primary.withValues(alpha: .3)),
      ),
      child: Column(
        children: [
          const SizedBox(
            width: 36,
            height: 36,
            child: CircularProgressIndicator(
                strokeWidth: 3, valueColor: AlwaysStoppedAnimation(AppColors.primary)),
          ),
          const SizedBox(height: 16),
          const Text('AI 正在分析你的体态…',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          Text('通常需要 5-10 秒',
              style: TextStyle(
                  color: AppColors.textSecondary,
                  fontSize: 12)),
        ],
      ),
    );
  }

  Widget _resultCard(Assessment r) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(
            color: Theme.of(context).brightness == Brightness.dark
                ? AppColors.trainingBorder
                : const Color(0xFFEDEFF2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.analytics_outlined,
                  color: AppColors.primary, size: 20),
              const SizedBox(width: 8),
              const Text('评估结果',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const Spacer(),
              DirectionBadge(direction: r.direction),
            ],
          ),
          if (r.bodyType != null && r.bodyType!.isNotEmpty) ...[
            const SizedBox(height: 14),
            _infoRow('体型判断', r.bodyType!),
          ],
          if (r.summary != null && r.summary!.isNotEmpty) ...[
            const SizedBox(height: 16),
            Text(r.summary!, style: const TextStyle(height: 1.6, fontSize: 14)),
          ],
          if (r.observed.isNotEmpty) ...[
            const SizedBox(height: 16),
            const Text('观察要点',
                style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
            const SizedBox(height: 8),
            ...r.observed.map((o) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Padding(
                        padding: EdgeInsets.only(top: 6),
                        child: CircleAvatar(
                            radius: 3, backgroundColor: AppColors.primary),
                      ),
                      const SizedBox(width: 10),
                      Expanded(child: Text(o, style: const TextStyle(fontSize: 13))),
                    ],
                  ),
                )),
          ],
          if (r.safetyNotes != null && r.safetyNotes!.isNotEmpty) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppColors.warning.withValues(alpha: .1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  const Icon(Icons.info_outline,
                      color: AppColors.warning, size: 18),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(r.safetyNotes!,
                        style: const TextStyle(
                            color: AppColors.warning, fontSize: 12)),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: () => Navigator.of(context).pop(r),
              icon: const Icon(Icons.assignment_add, color: Colors.black),
              label: const Text('用这个结果生成计划',
                  style: TextStyle(color: Colors.black)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _infoRow(String label, String value) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 64,
          child: Text(label,
              style: const TextStyle(color: AppColors.textSecondary, fontSize: 13)),
        ),
        Expanded(
          child: Text(value,
              style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
        ),
      ],
    );
  }

  void _showSourceSheet() {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_camera, color: AppColors.primary),
              title: const Text('拍照'),
              onTap: () {
                Navigator.pop(context);
                _pick(ImageSource.camera);
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('从相册选择'),
              onTap: () {
                Navigator.pop(context);
                _pick(ImageSource.gallery);
              },
            ),
          ],
        ),
      ),
    );
  }
}
