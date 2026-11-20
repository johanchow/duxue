import 'package:duxue_app/core/api_client.dart';
import 'package:duxue_app/core/models.dart';
import 'package:duxue_app/core/token_storage.dart';
import 'package:duxue_app/features/guardian_members_page.dart';
import 'package:duxue_app/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _MemberApi extends ApiClient {
  _MemberApi()
      : super(baseUrl: 'http://localhost', tokens: const TokenStorage());

  bool joined = false;

  @override
  Future<Map<String, dynamic>> guardianMembers() async => {
        'incoming': [
          if (!joined) {'id': 'invite', 'inviter': '妈妈', 'ward_name': '小宇'},
        ],
        'wards': [
          if (joined)
            {
              'id': 'ward',
              'name': '小宇',
              'can_manage': false,
              'can_leave': true,
              'members': [],
              'pending': [],
            },
        ]
      };

  @override
  Future<List<Ward>> wards() async => [
        if (joined)
          const Ward(id: 'ward', displayName: '小宇', gradeStage: 'primary'),
      ];

  @override
  Future<void> acceptGuardianInvite(String id) async {
    expect(id, 'invite');
    joined = true;
  }

  @override
  Future<void> removeGuardian(String wardId, String id) async {
    expect(wardId, 'ward');
    expect(id, 'me');
    joined = false;
  }
}

void main() {
  testWidgets('accept and leave refresh the child list', (tester) async {
    final api = _MemberApi();
    final container =
        ProviderContainer(overrides: [apiProvider.overrideWithValue(api)]);
    addTearDown(container.dispose);
    expect(await container.read(wardsProvider.future), isEmpty);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: GuardianMembersPage()),
    ));
    await tester.pumpAndSettle();
    expect(find.text('妈妈 邀请你共管 小宇'), findsOneWidget);
    await tester.tap(find.text('接受邀请'));
    await tester.pumpAndSettle();
    expect(find.text('邀请共管'), findsNothing);
    expect((await container.read(wardsProvider.future)).single.id, 'ward');
    await tester.tap(find.text('退出共管'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '退出共管'));
    await tester.pumpAndSettle();
    expect(await container.read(wardsProvider.future), isEmpty);
  });
}
