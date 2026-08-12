import 'package:flutter_test/flutter_test.dart';

import 'package:formfit_app/core/config.dart';

void main() {
  group('AppConfig 同源/相对路径', () {
    test('默认（非空）按 origin 拼接绝对媒体 URL', () {
      // apiBaseUrl 默认值在测试环境为 127.0.0.1:8000。
      expect(AppConfig.apiBaseUrl, isNotEmpty);
      expect(AppConfig.usesRelativeApi, isFalse);
      final url = AppConfig.resolveUrl('/media/x.gif');
      expect(url, '${AppConfig.apiBaseUrl}/media/x.gif');
    });

    test('已是绝对 URL 原样返回', () {
      const abs = 'https://cdn.example.com/a.gif';
      expect(AppConfig.resolveUrl(abs), abs);
    });

    test('空路径返回空串', () {
      expect(AppConfig.resolveUrl(null), '');
      expect(AppConfig.resolveUrl(''), '');
    });
  });
}
