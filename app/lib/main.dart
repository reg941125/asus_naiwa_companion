import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

void main() => runApp(const MilkFrogApp());

class MilkFrogApp extends StatelessWidget {
  const MilkFrogApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Milk Frog',
    theme: ThemeData(colorSchemeSeed: Colors.green, useMaterial3: true),
    home: const CompanionPage(),
  );
}

class CompanionPage extends StatefulWidget {
  const CompanionPage({super.key, this.client});
  final http.Client? client;
  @override
  State<CompanionPage> createState() => _CompanionPageState();
}

class _CompanionPageState extends State<CompanionPage> {
  final storage = const FlutterSecureStorage();
  late final http.Client client = widget.client ?? http.Client();
  final address = TextEditingController(text: 'https://milk-frog.local:8443');
  final code = TextEditingController();
  String? token;
  String message = 'Enter your local device address and physical pairing code.';
  List<Map<String, dynamic>> workflows = [];
  String? selected;
  bool permission = false;
  bool busy = false;
  bool quiet = false;

  @override
  void initState() {
    super.initState();
    restore();
  }

  Future<void> restore() async {
    final savedAddress = await storage.read(key: 'address');
    final savedToken = await storage.read(key: 'token');
    if (!mounted) return;
    if (savedAddress != null) address.text = savedAddress;
    token = savedToken;
    if (token != null) await perform(loadCatalog);
  }

  Uri endpoint(String path) {
    final uri = Uri.parse(address.text.trim());
    if (uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.query.isNotEmpty ||
        uri.fragment.isNotEmpty ||
        (uri.path.isNotEmpty && uri.path != '/')) {
      throw Exception('Use a local HTTPS origin with a trusted certificate.');
    }
    return uri.replace(path: path);
  }

  Future<http.Response> request(
    String path, {
    Object? body,
    bool delete = false,
  }) async {
    final headers = <String, String>{
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
    final uri = endpoint(path);
    final future = delete
        ? client.delete(uri, headers: headers)
        : body == null
        ? client.get(uri, headers: headers)
        : client.post(uri, headers: headers, body: jsonEncode(body));
    final result = await future.timeout(const Duration(seconds: 10));
    if (result.statusCode >= 400) {
      throw Exception(
        'Device rejected request (${result.statusCode}): ${result.body}',
      );
    }
    return result;
  }

  Future<void> perform(Future<void> Function() work) async {
    if (busy) return;
    setState(() => busy = true);
    try {
      await work();
    } catch (error) {
      if (mounted) setState(() => message = error.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> loadCatalog() async {
    final response = await request('/catalog');
    final values = (jsonDecode(response.body)['workflows'] as List)
        .map((w) => Map<String, dynamic>.from(w))
        .toList();
    if (!mounted) return;
    setState(() {
      workflows = values;
      selected = values.isEmpty ? null : values.first['id'] as String;
      message = 'Connected. Session feedback is spoken on your device.';
    });
  }

  Future<void> pair() async {
    token = null;
    final response = await request('/pair', body: {'code': code.text.trim()});
    token = jsonDecode(response.body)['token'] as String;
    await storage.write(key: 'token', value: token);
    await storage.write(key: 'address', value: address.text.trim());
    code.clear();
    await loadCatalog();
  }

  Future<void> command(String action) async {
    await request(
      '/commands',
      body: {
        'action': action,
        if (action == 'start') 'workflow_id': selected,
        if (action == 'start') 'permission_confirmed': permission,
        if (action == 'quiet') 'enabled': !quiet,
      },
    );
    if (!mounted) return;
    setState(() {
      if (action == 'quiet') quiet = !quiet;
      message = 'Command accepted. Listen to Milk Frog for session feedback.';
    });
  }

  Future<void> forgetConnection() async {
    await storage.delete(key: 'token');
    if (!mounted) return;
    setState(() {
      token = null;
      workflows = [];
      selected = null;
      permission = false;
      message =
          'Connection forgotten. Use a new physical code to pair a device.';
    });
  }

  Future<void> erase() async {
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete local data?'),
        content: const Text(
          'This stops the session, deletes local records and pack permissions, and unpairs this app.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (approved != true) return;
    await request('/local-data', delete: true);
    await storage.delete(key: 'token');
    if (!mounted) return;
    setState(() {
      token = null;
      workflows = [];
      selected = null;
      message = 'Local data deleted. Restart the device to pair again.';
    });
  }

  @override
  void dispose() {
    if (widget.client == null) client.close();
    address.dispose();
    code.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Milk Frog Companion')),
    body: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 600),
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const Icon(Icons.eco, size: 72, color: Colors.green),
            const Text(
              'A familiar companion for your daily routine',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            TextField(
              controller: address,
              enabled: !busy && token == null,
              decoration: const InputDecoration(
                labelText: 'Local device HTTPS address',
              ),
            ),
            if (token == null) ...[
              TextField(
                controller: code,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: const InputDecoration(
                  labelText: 'Physical pairing code',
                ),
              ),
              FilledButton(
                onPressed: busy ? null : () => perform(pair),
                child: const Text('Pair device'),
              ),
            ],
            if (token != null)
              TextButton(
                onPressed: busy ? null : () => perform(forgetConnection),
                child: const Text('Forget this connection'),
              ),
            if (workflows.isNotEmpty) ...[
              DropdownButtonFormField<String>(
                initialValue: selected,
                decoration: const InputDecoration(labelText: 'Approved plan'),
                items: workflows
                    .map(
                      (w) => DropdownMenuItem<String>(
                        value: w['id'] as String,
                        child: Text('${w['mode']}: ${w['title']}'),
                      ),
                    )
                    .toList(),
                onChanged: busy
                    ? null
                    : (value) => setState(() {
                        selected = value;
                        permission = false;
                      }),
              ),
              CheckboxListTile(
                value: permission,
                title: const Text(
                  'I have permission to use this kitchen or supervised workspace',
                ),
                onChanged: busy
                    ? null
                    : (value) => setState(() => permission = value ?? false),
              ),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final entry in {
                    'start': 'Start',
                    'confirm': 'Confirm step',
                    'pause': 'Pause',
                    'resume': 'Resume',
                    'stop': 'Stop',
                    'snooze': 'Snooze',
                    'quiet': quiet ? 'Enable voice' : 'Quiet',
                  }.entries)
                    FilledButton.tonal(
                      onPressed: busy
                          ? null
                          : () => perform(() => command(entry.key)),
                      child: Text(entry.value),
                    ),
                ],
              ),
              TextButton(
                onPressed: busy ? null : () => perform(erase),
                child: const Text('Delete local data and unpair'),
              ),
            ],
            const SizedBox(height: 24),
            if (busy) const LinearProgressIndicator(),
            Text(message, semanticsLabel: message),
            const SizedBox(height: 16),
            const Text('Camera, audio and session records stay on Milk Frog.'),
          ],
        ),
      ),
    ),
  );
}
