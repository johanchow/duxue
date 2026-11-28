import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/features/education_document.dart';
import 'package:duxue_app/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Documents extends ApiClient {
  _Documents()
      : super(baseUrl: 'http://localhost', tokens: const TokenStorage());
  final doc = <String, dynamic>{
    'title': '作业批改诊断',
    'state_revision': 1,
    'blocks': [
      {
        'kind': 'grading_item',
        'page': 2,
        'label': '1',
        'stem': '读图填空',
        'status': 'needs_manual_review',
        'student_answer': '',
        'explanation': '图片遮挡'
      }
    ],
  };
  @override
  Future<Map<String, dynamic>> educationDocument(String id) async => doc;
  @override
  Future<Map<String, dynamic>> changeEducationDocument(
      String id, Map<String, dynamic> body) async {
    expect(body['action'], 'save');
    expect(body['expected_revision'], 1);
    return {...doc, 'saved': true, 'state_revision': 2};
  }
}

void main() {
  testWidgets('批改保留所在页、题号与人工复核原因，可以独立保存', (tester) async {
    await tester.pumpWidget(ProviderScope(
        overrides: [apiProvider.overrideWithValue(_Documents())],
        child: const MaterialApp(home: EducationDocumentPage(id: 'document'))));
    await tester.pumpAndSettle();
    expect(find.text('第 2 页 · 第 1 项'), findsOneWidget);
    expect(find.text('待人工复核'), findsOneWidget);
    expect(find.text('图片遮挡'), findsOneWidget);
    await tester.tap(find.text('保存到我的资源库'));
    await tester.pumpAndSettle();
    expect(find.text('已保存'), findsOneWidget);
  });
}
