import 'dart:io';
import 'dart:typed_data';

import 'package:cross_file/cross_file.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:formfit_app/api/repository.dart';

void main() {
  group('buildAssessMultipartFile 平台拆分', () {
    const bytes = [137, 80, 78, 71, 13, 10, 26, 10]; // PNG 魔数
    late Directory tmpDir;
    late File tmp;
    late XFile xfile;

    setUp(() async {
      tmpDir = await Directory.systemTemp.createTemp('formfit_upload');
      // native 下 XFile.name 取路径 basename（构造参数 name 被忽略），
      // 故直接把临时文件命名为 photo.png。
      tmp = File('${tmpDir.path}/photo.png');
      await tmp.writeAsBytes(bytes);
      xfile = XFile(tmp.path);
    });

    tearDown(() async {
      if (await tmpDir.exists()) {
        await tmpDir.delete(recursive: true);
      }
    });

    test('Web 分支：fromBytes，内容等于图片字节', () async {
      final f = await buildAssessMultipartFile(image: xfile, isWeb: true);
      expect(f.filename, 'photo.png');
      final collected = <int>[];
      await for (final chunk in f.finalize()) {
        collected.addAll(chunk);
      }
      expect(collected, bytes);
      expect(f.length, bytes.length);
    });

    test('native 分支：fromFile，内容等于图片字节', () async {
      final f = await buildAssessMultipartFile(image: xfile, isWeb: false);
      expect(f.filename, 'photo.png');
      final collected = <int>[];
      await for (final chunk in f.finalize()) {
        collected.addAll(chunk);
      }
      expect(collected, bytes);
      expect(f.length, bytes.length);
    });

    test('Web 分支：文件名为空时回退 photo.jpg', () async {
      // XFile.fromData 不传 path 时，native 测试环境下 name 为空串，
      // 可验证回退逻辑；该用例只走 isWeb:true（fromBytes）。
      final x = XFile.fromData(Uint8List.fromList(bytes));
      expect(x.name, isEmpty);
      final f = await buildAssessMultipartFile(image: x, isWeb: true);
      expect(f.filename, 'photo.jpg');
    });
  });
}
