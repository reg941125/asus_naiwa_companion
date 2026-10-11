import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:milk_frog_app/main.dart';

const catalog = {
  'workflows': [
    {'id': 'study', 'mode': 'study', 'title': 'Study demo'},
    {'id': 'kitchen', 'mode': 'cooking', 'title': 'Cooking demo'},
  ],
};

Future<void> open(WidgetTester tester, MockClient client) async {
  await tester.pumpWidget(MaterialApp(home: CompanionPage(client: client)));
  await tester.pumpAndSettle();
}

Future<void> tap(
  WidgetTester tester,
  String label, {
  bool settle = true,
}) async {
  final button = find.text(label);
  await tester.ensureVisible(button);
  await tester.tap(button);
  if (settle) {
    await tester.pumpAndSettle();
  } else {
    await tester.pump(const Duration(milliseconds: 300));
  }
}

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  testWidgets('pairing stores credentials and loads only static plans', (
    tester,
  ) async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      if (request.url.path == '/pair') {
        expect(jsonDecode(request.body), {'code': '123456'});
        expect(request.headers['authorization'], isNull);
        return http.Response(
          '{"token":"paired-token","device_id":"demo"}',
          200,
        );
      }
      expect(request.url.path, '/catalog');
      expect(request.headers['authorization'], 'Bearer paired-token');
      return http.Response(jsonEncode(catalog), 200);
    });
    await open(tester, client);
    await tester.enterText(find.byType(TextField).last, '123456');
    await tap(tester, 'Pair device');
    expect(find.text('Start'), findsOneWidget);
    expect(requests.map((r) => r.url.path), ['/pair', '/catalog']);
    expect(
      await const FlutterSecureStorage().read(key: 'token'),
      'paired-token',
    );
    await tester.scrollUntilVisible(
      find.text('Connected. Session feedback is spoken on your device.'),
      150,
      scrollable: find.byType(Scrollable).first,
    );
    expect(
      find.text('Connected. Session feedback is spoken on your device.'),
      findsOneWidget,
    );
  });

  testWidgets('HTTP address is rejected before network access', (tester) async {
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      return http.Response('{}', 200);
    });
    await open(tester, client);
    await tester.enterText(
      find.byType(TextField).first,
      'http://127.0.0.1:8000',
    );
    await tester.enterText(find.byType(TextField).last, '123456');
    await tap(tester, 'Pair device');
    expect(calls, 0);
    expect(find.textContaining('Use a local HTTPS origin'), findsOneWidget);
    expect(find.text('Pair device'), findsOneWidget);
  });

  testWidgets('rejected pairing displays error and permits retry', (
    tester,
  ) async {
    final client = MockClient(
      (request) async => http.Response('{"detail":"expired code"}', 403),
    );
    await open(tester, client);
    await tester.enterText(find.byType(TextField).last, '123456');
    await tap(tester, 'Pair device');
    expect(find.textContaining('403'), findsOneWidget);
    expect(find.text('Pair device'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNothing);
  });

  testWidgets('restored connection sends commands and quiet toggle payloads', (
    tester,
  ) async {
    FlutterSecureStorage.setMockInitialValues({
      'token': 'saved',
      'address': 'https://localhost:8443',
    });
    final commands = <Map<String, dynamic>>[];
    final client = MockClient((request) async {
      expect(request.headers['authorization'], 'Bearer saved');
      if (request.url.path == '/catalog') {
        return http.Response(jsonEncode(catalog), 200);
      }
      expect(request.url.path, '/commands');
      commands.add(Map<String, dynamic>.from(jsonDecode(request.body)));
      return http.Response('', 204);
    });
    await open(tester, client);
    await tap(tester, 'Start');
    await tap(tester, 'Confirm step');
    await tap(tester, 'Quiet');
    await tap(tester, 'Enable voice');
    expect(commands, [
      {
        'action': 'start',
        'workflow_id': 'study',
        'permission_confirmed': false,
      },
      {'action': 'confirm'},
      {'action': 'quiet', 'enabled': true},
      {'action': 'quiet', 'enabled': false},
    ]);
  });

  testWidgets(
    'offline restored credentials can be forgotten and paired again',
    (tester) async {
      FlutterSecureStorage.setMockInitialValues({
        'token': 'old',
        'address': 'https://localhost:8443',
      });
      final client = MockClient(
        (request) async => throw http.ClientException('Device offline'),
      );
      await open(tester, client);
      expect(find.textContaining('Device offline'), findsOneWidget);
      await tap(tester, 'Forget this connection');
      expect(find.text('Pair device'), findsOneWidget);
      expect(await const FlutterSecureStorage().read(key: 'token'), isNull);
    },
  );

  testWidgets('data deletion requires confirmation and clears credentials', (
    tester,
  ) async {
    FlutterSecureStorage.setMockInitialValues({'token': 'saved'});
    var deletions = 0;
    final client = MockClient((request) async {
      if (request.url.path == '/catalog') {
        return http.Response(jsonEncode(catalog), 200);
      }
      expect(request.method, 'DELETE');
      expect(request.url.path, '/local-data');
      deletions++;
      return http.Response('', 204);
    });
    await open(tester, client);
    await tap(tester, 'Delete local data and unpair', settle: false);
    await tap(tester, 'Cancel');
    expect(deletions, 0);
    await tap(tester, 'Delete local data and unpair', settle: false);
    await tap(tester, 'Delete');
    expect(deletions, 1);
    expect(await const FlutterSecureStorage().read(key: 'token'), isNull);
    expect(find.text('Pair device'), findsOneWidget);
  });
}
