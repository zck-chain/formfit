import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:formfit_app/app.dart';

void main() {
  testWidgets('App boots to splash', (WidgetTester tester) async {
    await tester.pumpWidget(const ProviderScope(child: FormFitApp()));
    await tester.pump();
    // 启动闪屏应显示品牌名
    expect(find.text('FormFit'), findsOneWidget);
  });
}
